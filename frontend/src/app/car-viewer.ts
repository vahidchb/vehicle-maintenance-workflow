// نمایشگر سه‌بعدی خودرو — Three.js + مدل GLB
// مدل: samand.glb — سمند X7 از Sketchfab (Mpgs.studio3DModels، CC-BY-4.0)،
// با gltfpack -cc از دانلود glTF اسکچ‌فب به یک GLB فشرده تبدیل شده است.
// اگر مدل لود نشود، کامپوننت رویداد loadFailed را می‌فرستد و کامپوننت
// والد (App) گردونه عکس را به‌جای آن نشان می‌دهد.
import {
  AfterViewInit,
  Component,
  ElementRef,
  EventEmitter,
  NgZone,
  OnDestroy,
  Output,
  ViewChild,
  signal,
} from '@angular/core';
import type * as THREE from 'three';
import type { OrbitControls } from 'three/addons/controls/OrbitControls.js';

// مسیر مدل سه‌بعدی — برای عوض کردن خودرو بعدا کافی است این خط را
// عوض کنی (sedan.glb سدان تستی به‌عنوان یدکی در همان پوشه مانده است).
// نمای منفجرشده شعاعی است و روی هر مدلی که مش‌های مستقیم صحنه
// یا گروه GLTF_SceneRootNode داشته باشد کار می‌کند.
const MODEL_URL = '/models/samand.glb';
// اندازه هدف خودرو در صحنه (طولانی‌ترین بُعد)، بر حسب واحد صحنه
// (مدل سمند در واحد خامش خیلی بزرگ است — حدود ۷۴ واحد — و همین تناسب
// آن را به اندازه صحنه کوچک می‌کند؛ پس دوربین و کف دست نمی‌خورند)
const TARGET_SIZE = 3.2;
// فاصله دوربین از مرکز خودرو
const CAMERA_DISTANCE = 5.2;
// چند ثانیه بعد از رها کردن درگ، چرخش خودکار برگردد
const AUTOROTATE_RESUME_MS = 3000;
// چقدر قطعه‌ها موقع انفجار از هم دور شوند (واحد جهان صحنه — نه محلی مدل)
const EXPLODE_DISTANCE = 0.45;
// چرخ‌ها این‌قدر بیشتر از بقیه قطعه‌ها بیرون می‌روند
const WHEEL_EXPLODE_FACTOR = 1.6;
// قطعه‌ای که مرکزش از مرکز خودرو کمتر از این کسرِ قطر مدل فاصله دارد،
// «وسط خودرو» حساب می‌شود و به بالا می‌رود (تکه‌های بدنه)
const CENTERED_PART_THRESHOLD = 0.08;

type ViewerState = 'loading' | 'ready' | 'error';

// یک قطعه قابل انفجار: گره + جای اولش + جهت محلی + فاصله محلی انفجار
// (جهت و فاصله در فضای محلی والد قطعه‌اند، چون والد ممکن است چرخش/مقیاس داشته باشد)
interface ExplodablePart {
  node: THREE.Object3D;
  home: THREE.Vector3;
  dir: THREE.Vector3;
  dist: number;
}

@Component({
  selector: 'app-car-viewer',
  templateUrl: './car-viewer.html',
  styleUrl: './car-viewer.css',
})
export class CarViewerComponent implements AfterViewInit, OnDestroy {
  // اگر مدل لود نشد، والد گردونه عکس را نشان می‌دهد
  @Output() loadFailed = new EventEmitter<void>();

  @ViewChild('container', { static: true }) private container!: ElementRef<HTMLDivElement>;

  // وضعیت لود + حالت منفجرشده (برای template)
  state = signal<ViewerState>('loading');
  exploded = signal(false);

  // فضای نام three — با dynamic import لود می‌شود تا باندل اولیه سبک بماند
  // (three در یک چانک جدا می‌آید و فقط وقتی این کامپوننت باز شود دانلود می‌شود)
  private three: typeof import('three') | null = null;
  private renderer: THREE.WebGLRenderer | null = null;
  private controls: OrbitControls | null = null;
  private scene: THREE.Scene | null = null;
  private camera: THREE.PerspectiveCamera | null = null;
  private resizeObserver: ResizeObserver | null = null;
  private frameId = 0;
  private destroyed = false;
  private resumeTimer: ReturnType<typeof setTimeout> | null = null;
  // قطعه‌های انفجار + مقدار فعلی انفجار (۰ بسته، ۱ باز) برای انیمیشن نرم
  private parts: ExplodablePart[] = [];
  private explodeFactor = 0;
  private explodeTarget = 0;

  constructor(private ngZone: NgZone) {}

  ngAfterViewInit() {
    void this.init();
  }

  ngOnDestroy() {
    this.destroyed = true;
    cancelAnimationFrame(this.frameId);
    if (this.resumeTimer !== null) clearTimeout(this.resumeTimer);
    this.resizeObserver?.disconnect();
    this.controls?.dispose();
    // حافظه GPU را آزاد کن (هندسه و متریال همه مش‌ها)
    this.scene?.traverse((obj) => {
      const mesh = obj as THREE.Mesh;
      mesh.geometry?.dispose();
      const material = mesh.material as THREE.Material | THREE.Material[] | undefined;
      if (Array.isArray(material)) material.forEach((m) => m.dispose());
      else material?.dispose();
    });
    this.renderer?.dispose();
    this.renderer?.domElement.remove();
    this.renderer = null;
    this.controls = null;
    this.scene = null;
    this.camera = null;
  }

  // دکمه نمایش منفجرشده / بازگشت به حالت عادی
  toggleExplode() {
    const next = !this.exploded();
    this.exploded.set(next);
    this.explodeTarget = next ? 1 : 0;
  }

  // --- راه‌اندازی: لود three، ساخت صحنه، لود مدل ---
  private async init() {
    try {
      const THREE = await import('three');
      if (this.destroyed) return;
      this.three = THREE;
      const { OrbitControls } = await import('three/addons/controls/OrbitControls.js');
      const { GLTFLoader } = await import('three/addons/loaders/GLTFLoader.js');
      const { RoomEnvironment } = await import('three/addons/environments/RoomEnvironment.js');
      const { MeshoptDecoder } = await import('three/addons/libs/meshopt_decoder.module.js');
      if (this.destroyed) return;

      this.buildScene(THREE, OrbitControls, RoomEnvironment);
      this.loadModel(GLTFLoader, MeshoptDecoder);
      this.startLoop();
    } catch {
      this.fail();
    }
  }

  // صحنه: رندرر + دوربین + نور سینمایی + کف + کنترل چرخش
  private buildScene(
    THREE: typeof import('three'),
    OrbitControls: typeof import('three/addons/controls/OrbitControls.js').OrbitControls,
    RoomEnvironment: typeof import('three/addons/environments/RoomEnvironment.js').RoomEnvironment,
  ) {
    const el = this.container.nativeElement;
    const width = el.clientWidth || 640;
    const height = el.clientHeight || 420;

    // رندرر: بک‌گراند شفاف تا تم تیره صفحه دیده شود
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(width, height);
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.05;
    el.appendChild(renderer.domElement);
    this.renderer = renderer;

    const scene = new THREE.Scene();
    this.scene = scene;

    const camera = new THREE.PerspectiveCamera(40, width / height, 0.1, 100);
    camera.position.set(CAMERA_DISTANCE * 0.9, 2.4, CAMERA_DISTANCE * 0.9);
    this.camera = camera;

    // محیط بازتاب PBR — بدون آن بدنه مات و بی‌روح می‌شود
    const pmrem = new THREE.PMREMGenerator(renderer);
    scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    pmrem.dispose();

    // نور: نیم‌کره + نور کلیدی با سایه + نور قرمز لبه (تم #E10600)
    scene.add(new THREE.HemisphereLight(0xffffff, 0x1a1a1e, 0.55));
    const key = new THREE.DirectionalLight(0xffffff, 2.2);
    key.position.set(4, 6, 3);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    key.shadow.camera.left = -3;
    key.shadow.camera.right = 3;
    key.shadow.camera.top = 3;
    key.shadow.camera.bottom = -3;
    key.shadow.camera.far = 20;
    key.shadow.bias = -0.0005;
    scene.add(key);
    const rim = new THREE.PointLight(0xe10600, 30, 14, 2);
    rim.position.set(-3.5, 1.6, -3);
    scene.add(rim);

    // کف: دیسک نامرئی که فقط سایه را می‌گیرد
    const ground = new THREE.Mesh(
      new THREE.CircleGeometry(3.2, 48),
      new THREE.ShadowMaterial({ opacity: 0.35 }),
    );
    ground.rotation.x = -Math.PI / 2;
    ground.receiveShadow = true;
    scene.add(ground);

    // کنترل چرخش: درگ ۳۶۰ درجه، زوم، چرخش خودکار؛ پن (جابه‌جایی) خاموش
    // تا خودرو همیشه وسط صحنه بماند
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.06;
    controls.enablePan = false;
    controls.minDistance = 3;
    controls.maxDistance = 9;
    controls.maxPolarAngle = Math.PI * 0.495;
    controls.target.set(0, 0.7, 0);
    controls.autoRotate = true;
    controls.autoRotateSpeed = 1.1;
    controls.addEventListener('start', () => this.onInteractStart());
    controls.addEventListener('end', () => this.onInteractEnd());
    this.controls = controls;

    // اندازه صفحه با تغییر سایز کانتینر
    this.resizeObserver = new ResizeObserver(() => this.onResize());
    this.resizeObserver.observe(el);
  }

  // لود مدل GLB — با MeshoptDecoder چون مدل با meshopt فشرده شده است
  private loadModel(
    GLTFLoader: typeof import('three/addons/loaders/GLTFLoader.js').GLTFLoader,
    MeshoptDecoder: typeof import('three/addons/libs/meshopt_decoder.module.js').MeshoptDecoder,
  ) {
    const loader = new GLTFLoader();
    // بدون این خط مدل لود نمی‌شود (extensionsRequired شامل EXT_meshopt_compression است)
    loader.setMeshoptDecoder(MeshoptDecoder);
    loader.load(
      MODEL_URL,
      (gltf) => {
        if (this.destroyed) return;
        this.placeCar(gltf.scene);
        this.state.set('ready');
      },
      undefined,
      () => this.fail(),
    );
  }

  // خودرو را وسط صحنه بگذار، به اندازه هدف بزرگ کن و کف آن را روی زمین بگذار
  private placeCar(car: THREE.Group) {
    const THREE = this.three;
    if (!THREE) return;
    const box = new THREE.Box3().setFromObject(car);
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    const scale = TARGET_SIZE / Math.max(size.x, size.y, size.z);
    car.scale.setScalar(scale);
    car.position.set(-center.x * scale, -box.min.y * scale, -center.z * scale);
    // سایه + بازتاب ملایم برای همه مش‌ها
    car.traverse((obj) => {
      const mesh = obj as THREE.Mesh;
      if (!mesh.isMesh) return;
      mesh.castShadow = true;
      const material = mesh.material as THREE.MeshStandardMaterial | undefined;
      if (material && 'envMapIntensity' in material) material.envMapIntensity = 0.7;
    });
    this.scene?.add(car);
    this.collectParts(car);
  }

  // قطعه‌های انفجار — انفجار شعاعی (radial) روی ریشه‌های قطعه:
  // (الف) مش‌های مستقیم صحنه (تکه‌های بدنه که gltfpack ادغام کرده)
  // (ب) بچه‌های گروه GLTF_SceneRootNode (۴ گروه چرخ Tire_* + قطعه‌های کوچک)
  // جهت هر قطعه از مرکز خودرو به سمت مرکز خودش است؛ چرخ‌ها بیشتر بیرون می‌روند.
  // قطعه‌ای که مرکزش وسط خودروست (تکه بدنه) به بالا می‌رود، با ارتفاع پلکانی
  // تا تکه‌ها روی هم نمانند. جهت و فاصله به فضای محلی والد برگردانده می‌شود،
  // چون گره‌های والد (مثل GLTF_SceneRootNode) ممکن است چرخش/مقیاس داشته باشند.
  private collectParts(car: THREE.Group) {
    const THREE = this.three;
    if (!THREE) return;
    this.parts = [];
    car.updateMatrixWorld(true);

    // مرکز و اندازه کل خودرو (بعد از جای‌گذاری وسط صحنه)
    const modelBox = new THREE.Box3().setFromObject(car);
    const modelCenter = modelBox.getCenter(new THREE.Vector3());
    const modelDiagonal = modelBox.getSize(new THREE.Vector3()).length();

    // ریشه‌های قطعه را جمع کن:
    // (الف) بچه‌های مستقیم صحنه که مش دارند — مش مستقیم یا گروه چند-متریال
    // (مدلی با چند متریال در GLTFLoader یک گروه می‌شود، نه یک مش)
    // (ب) بچه‌های گروه GLTF_SceneRootNode (۴ گروه چرخ Tire_* + قطعه‌های کوچک)
    const sceneRoot = car.getObjectByName('GLTF_SceneRootNode');
    // شاخه‌ای از صحنه که GLTF_SceneRootNode زیر آن است (گروه Sketchfab_model) —
    // قطعه‌هایش را جداگانه از بچه‌های GLTF_SceneRootNode می‌گیریم، نه خودش را
    let sceneRootBranch: THREE.Object3D | null = null;
    if (sceneRoot) {
      sceneRootBranch = sceneRoot;
      while (sceneRootBranch.parent && sceneRootBranch.parent !== car) {
        sceneRootBranch = sceneRootBranch.parent;
      }
    }
    const roots: THREE.Object3D[] = [];
    for (const child of car.children) {
      if (child === sceneRootBranch) continue;
      let hasMesh = false;
      child.traverse((obj) => {
        if ((obj as THREE.Mesh).isMesh) hasMesh = true;
      });
      if (hasMesh) roots.push(child);
    }
    if (sceneRoot) roots.push(...sceneRoot.children);

    const partBox = new THREE.Box3();
    const partCenter = new THREE.Vector3();
    let centeredIndex = 0;
    for (const root of roots) {
      partBox.setFromObject(root);
      if (partBox.isEmpty()) continue;
      partBox.getCenter(partCenter);
      // چرخ است؟ نام گره با Tire شروع می‌شود (نقطه و خط زیرین را حذف کن،
      // چون در بعضی لودرها Tire.001 به Tire001 تبدیل می‌شود)
      const isWheel = root.name.toLowerCase().replace(/[^a-z0-9]/g, '').startsWith('tire');
      const dirWorld = partCenter.clone().sub(modelCenter);
      let factor: number;
      if (dirWorld.length() < modelDiagonal * CENTERED_PART_THRESHOLD) {
        // مرکزش وسط خودروست — به بالا، با ارتفاع پلکانی
        dirWorld.set(0, 1, 0);
        factor = 0.4 + 0.25 * centeredIndex;
        centeredIndex++;
      } else {
        dirWorld.normalize();
        factor = isWheel ? WHEEL_EXPLODE_FACTOR : 1;
      }
      // جهت را به فضای محلی والد برگردان (چرخش والد را خنثی کن)
      const parent = root.parent ?? car;
      const dirLocal = dirWorld.clone().transformDirection(parent.matrixWorld.clone().invert());
      // فاصله را به واحد محلی والد تبدیل کن (مقیاس والد را تقسیم کن)
      const parentScale = parent.getWorldScale(new THREE.Vector3()).x || 1;
      this.parts.push({
        node: root,
        home: root.position.clone(),
        dir: dirLocal,
        dist: (EXPLODE_DISTANCE * factor) / parentScale,
      });
    }
  }

  // حلقه رندر — بیرون از zone انگولار تا change detection هر فریم اجرا نشود
  private startLoop() {
    this.ngZone.runOutsideAngular(() => {
      let last = performance.now();
      const tick = (now: number) => {
        if (this.destroyed) return;
        const dt = Math.min((now - last) / 1000, 0.05);
        last = now;
        // انیمیشن نرم انفجار: مقدار فعلی به سمت هدف میل می‌کند
        this.explodeFactor += (this.explodeTarget - this.explodeFactor) * Math.min(1, dt * 4);
        if (Math.abs(this.explodeTarget - this.explodeFactor) < 0.001) {
          this.explodeFactor = this.explodeTarget;
        }
        this.applyExplode();
        this.controls?.update();
        if (this.renderer && this.scene && this.camera) {
          this.renderer.render(this.scene, this.camera);
        }
        this.frameId = requestAnimationFrame(tick);
      };
      this.frameId = requestAnimationFrame(tick);
    });
  }

  // جای هر قطعه را بر اساس مقدار فعلی انفجار تنظیم کن
  private applyExplode() {
    for (const part of this.parts) {
      part.node.position.copy(part.home).addScaledVector(part.dir, part.dist * this.explodeFactor);
    }
  }

  // موقع درگ، چرخش خودکار مکث می‌کند؛ چند ثانیه بعد از رها کردن برمی‌گردد
  private onInteractStart() {
    if (this.controls) this.controls.autoRotate = false;
    if (this.resumeTimer !== null) clearTimeout(this.resumeTimer);
  }

  private onInteractEnd() {
    if (this.resumeTimer !== null) clearTimeout(this.resumeTimer);
    this.resumeTimer = setTimeout(() => {
      if (!this.destroyed && this.controls) this.controls.autoRotate = true;
    }, AUTOROTATE_RESUME_MS);
  }

  private onResize() {
    const el = this.container.nativeElement;
    const width = el.clientWidth;
    const height = el.clientHeight;
    if (!width || !height || !this.renderer || !this.camera) return;
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height);
  }

  // لود ناموفق (فایل نیست، WebGL نیست، یا خطای دیگر) — والد گردونه عکس را نشان می‌دهد
  private fail() {
    if (this.destroyed) return;
    this.state.set('error');
    this.loadFailed.emit();
  }
}
