// نمایشگر سه‌بعدی خودرو — Three.js + مدل GLB
// مدل: sedan.glb (Kenney Car Kit، CC0) در public/models/
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

// مسیر مدل سه‌بعدی — برای عوض کردن خودرو بعدا کافی است این فایل را
// با یک GLB دیگر عوض کنی (نام گره‌های چرخ باید با wheel- شروع شود
// و گره بدنه body باشد تا نمای منفجرشده کار کند)
const MODEL_URL = '/models/sedan.glb';
// اندازه هدف خودرو در صحنه (طولانی‌ترین بُعد)، بر حسب واحد صحنه
const TARGET_SIZE = 3.2;
// فاصله دوربین از مرکز خودرو
const CAMERA_DISTANCE = 5.2;
// چند ثانیه بعد از رها کردن درگ، چرخش خودکار برگردد
const AUTOROTATE_RESUME_MS = 3000;
// چقدر قطعه‌ها موقع انفجار از هم دور شوند (واحد محلی مدل)
const EXPLODE_DISTANCE = 0.45;

type ViewerState = 'loading' | 'ready' | 'error';

// یک قطعه قابل انفجار: گره + جای اولش + جهتی که موقع انفجار می‌رود
interface ExplodablePart {
  node: THREE.Object3D;
  home: THREE.Vector3;
  dir: THREE.Vector3;
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

  // قطعه‌های انفجار را از روی نام گره پیدا کن: چرخ‌ها (wheel-*) + بدنه (body)
  private collectParts(car: THREE.Group) {
    const THREE = this.three;
    if (!THREE) return;
    this.parts = [];
    car.traverse((obj) => {
      const name = obj.name.toLowerCase();
      if (name.startsWith('wheel-')) {
        // چرخ: به بیرون (علامت x) و کمی پایین
        const dir = new THREE.Vector3(Math.sign(obj.position.x) || 1, -0.4, 0).normalize();
        this.parts.push({ node: obj, home: obj.position.clone(), dir });
      } else if (name === 'body') {
        // بدنه: بالا
        this.parts.push({ node: obj, home: obj.position.clone(), dir: new THREE.Vector3(0, 1, 0) });
      }
    });
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
      part.node.position.copy(part.home).addScaledVector(part.dir, EXPLODE_DISTANCE * this.explodeFactor);
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
