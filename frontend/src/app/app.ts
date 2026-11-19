import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { forkJoin } from 'rxjs';
import { ApiService, ModuleInfo, PendingConfirmation, StageInfo } from './api.service';
import { CarViewerComponent } from './car-viewer';

interface ChatMessage {
  role: 'user' | 'bot';
  text: string;
  usedTool?: boolean;
}

// یک گروه از سوابق یک خودرو، برای مودال گاراژ
interface VehicleRecordGroup {
  key: string;
  label: string;
  items: { tracking: string; line: string }[];
}

type View = 'home' | 'garage' | 'chat' | 'articles' | 'grid' | 'modules';

// ستون‌های هر گرید: کلید فیلد + برچسب فارسی
const COLUMNS: Record<string, { key: string; label: string }[]> = {
  equipment: [
    { key: 'tracking', label: 'رهگیری' },
    { key: 'plate', label: 'پلاک' },
    { key: 'name', label: 'نام' },
    { key: 'kind', label: 'نوع' },
  ],
  inspections: [
    { key: 'tracking', label: 'رهگیری' },
    { key: 'plate', label: 'پلاک' },
    { key: 'subsystem', label: 'زیرمجموعه' },
    { key: 'note', label: 'توضیح' },
  ],
  evaluations: [
    { key: 'tracking', label: 'رهگیری' },
    { key: 'plate', label: 'پلاک' },
    { key: 'inspection_id', label: 'بازدید' },
    { key: 'summary', label: 'خلاصه' },
  ],
  faults: [
    { key: 'tracking', label: 'رهگیری' },
    { key: 'evaluation_id', label: 'ارزیابی' },
    { key: 'plate', label: 'پلاک' },
    { key: 'subsystem', label: 'زیرمجموعه' },
    { key: 'description', label: 'شرح خرابی' },
  ],
  requests: [
    { key: 'tracking', label: 'رهگیری' },
    { key: 'plate', label: 'پلاک' },
    { key: 'evaluation_id', label: 'ارزیابی' },
    { key: 'fault_id', label: 'خرابی' },
    { key: 'status', label: 'وضعیت' },
    { key: 'description', label: 'شرح' },
  ],
  work_orders: [
    { key: 'tracking', label: 'رهگیری' },
    { key: 'request_id', label: 'درخواست' },
    { key: 'plate', label: 'پلاک' },
    { key: 'shop', label: 'تعمیرگاه' },
    { key: 'parts', label: 'قطعات' },
    { key: 'status', label: 'وضعیت' },
  ],
};

// برچسب فارسی فیلدها، برای نمایش جزئیات یک رکورد
const FIELD_LABELS: Record<string, string> = {
  tracking: 'شماره رهگیری',
  plate: 'پلاک',
  name: 'نام',
  kind: 'نوع',
  subsystem: 'زیرمجموعه',
  note: 'توضیح',
  inspection_id: 'بازدید',
  summary: 'خلاصه',
  evaluation_id: 'ارزیابی',
  description: 'شرح',
  fault_id: 'خرابی',
  request_id: 'درخواست',
  status: 'وضعیت',
  shop: 'تعمیرگاه',
  parts: 'قطعات',
};

// هر مرحله workflow به کدام ماژول وصل است (برای نمودار ماژول‌ها)
const STAGE_MODULE: Record<string, string> = {
  equipment: 'equipment',
  inspection: 'inspections',
  evaluation: 'evaluations',
  fault: 'faults',
  repair_request: 'requests',
  approval: 'requests',
  work_order: 'work_orders',
};

// گروه‌های سوابق یک خودرو در مودال گاراژ: کلید ماژول + برچسب + چطور یک خط خلاصه بساز
const VEHICLE_GROUPS: { key: string; label: string; line: (r: Record<string, unknown>) => string }[] = [
  { key: 'inspections', label: 'بازدیدها', line: (r) => `${r['subsystem'] ?? ''}${r['note'] ? ' — ' + r['note'] : ''}` },
  { key: 'evaluations', label: 'ارزیابی‌ها', line: (r) => String(r['summary'] ?? '') },
  { key: 'faults', label: 'خرابی‌ها', line: (r) => String(r['description'] ?? '') },
  { key: 'requests', label: 'درخواست‌های تعمیراتی', line: (r) => `${r['status'] ?? ''}${r['description'] ? ' — ' + r['description'] : ''}` },
  { key: 'work_orders', label: 'حکم کارها', line: (r) => `${r['shop'] ?? ''} — قطعات: ${r['parts'] ?? ''}` },
];

// --- گردونه سه‌بعدی صفحه خانه (Turntable) ---
// ۷ زاویه از یک دنا پلاس قرمز، با یک بک‌گراند استودیویی؛ ترتیب = چرخش جلو به عقب.
// برای عوض کردن خودرو بعدا کافی است فایل‌های پوشه public/turntable/ را عوض کنی
// و همین لیست را به‌روز کنی — بقیه کد (چرخش، نقطه‌ها، درگ) دست نمی‌خورد.
const TURNTABLE_IMAGES: string[] = [
  '/turntable/dena-0007.jpg', // جلو
  '/turntable/dena-0001.jpg', // جلو سه‌ربع
  '/turntable/dena-0002.jpg', // کنار (جلو)
  '/turntable/dena-0003.jpg', // کنار (عقب)
  '/turntable/dena-0004.jpg', // عقب سه‌ربع
  '/turntable/dena-0005.jpg', // عقب
  '/turntable/dena-0006.jpg', // عقب سه‌ربع (سمت دیگر)
];

@Component({
  selector: 'app-root',
  imports: [FormsModule, CarViewerComponent],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App {
  private api = inject(ApiService);

  // --- نما: خانه، گاراژ، چت، سرچ مقاله، گرید، یا نمودار ماژول‌ها ---
  view = signal<View>('home');

  // --- نمایشگر سه‌بعدی صفحه خانه ---
  // اگر مدل سه‌بعدی لود نشد (فایل نیست یا WebGL نیست)، نمایشگر رویداد
  // loadFailed می‌فرستد و گردونه عکس به‌جای آن نشان داده می‌شود
  viewerFailed = signal(false);

  onViewerFailed() {
    this.viewerFailed.set(true);
  }

  // --- گردونه سه‌بعدی صفحه خانه ---
  // لیست عکس‌ها (برای template؛ ترتیب چرخش در TURNTABLE_IMAGES است)
  turntableImages = TURNTABLE_IMAGES;
  // زاویه فعلی
  turntableIndex = signal(0);
  // مکث چرخش خودکار وقتی موس روی صحنه است
  turntablePaused = signal(false);
  // جهت چرخش خودکار: ۱ جلو به عقب، ۱- برگشت — رفت و برگشت (ping-pong)
  // تا چرخه بدون پرش ناگهانی به جلو برگردد
  private turntableDirection: 1 | -1 = 1;
  // نقطه شروع درگ، برای چرخاندن دستی با موس/لمس (null یعنی درگ فعال نیست)
  private dragStartX: number | null = null;

  constructor() {
    // آمار صفحه خانه (تعداد رکورد هر ماژول) را از اول بارگذاری کن
    this.refreshModules();
    // چرخش خودکار گردونه: هر ۳ ثانیه یک زاویه — این کامپوننت روت است و
    // تا پایان عمر اپ زنده می‌ماند، پس تایمر نیازی به پاک شدن ندارد
    setInterval(() => this.autoTurntable(), 3000);
  }

  // --- چت ---
  messages = signal<ChatMessage[]>([
    { role: 'bot', text: 'سلام! من چت‌بات نگهداری و تعمیرات هستم. مثلا بگو: «یک خودروی پراید با پلاک 12ب345 ایران 67 ثبت کن» یا «لیست ارزیابی‌ها را نشان بده».' },
  ]);
  input = signal('');
  loading = signal(false);
  tokens = signal(0);
  maxTokens = signal(4000);
  sessionId: string | null = null;

  // --- سرچ مقاله: چت جدا با هیستوری و جلسه جدا (تاریخچه چت اصلی اینجا نیست) ---
  articleMessages = signal<ChatMessage[]>([
    { role: 'bot', text: 'اینجا فقط سرچ مقاله است. مثلا بگو: «مقاله درباره نگهداری موتور خودرو پیدا کن»؛ تاریخچه چت اصلی اینجا نمایش داده نمی‌شود.' },
  ]);
  articleInput = signal('');
  articleLoading = signal(false);
  articleTokens = signal(0);
  articleMaxTokens = signal(4000);
  articleSessionId: string | null = null;

  // --- مودال تایید درخواست تعمیراتی ---
  pendingConfirmation = signal<PendingConfirmation | null>(null);
  confirming = signal(false);
  // جلسه چتی که تاییدیه از آن آمده (چت اصلی یا سرچ مقاله)
  confirmationSessionId: string | null = null;

  // --- گاراژ: همه رکوردها، با کلید ماژول (برای کارت‌ها، مرحله فعلی و مودال خودرو) ---
  garageRecords = signal<Record<string, Record<string, unknown>[]>>({});
  garageLoading = signal(false);
  garageError = signal('');
  // خودروی انتخاب‌شده در گاراژ؛ وقتی set است، مودالش باز است
  selectedVehicle = signal<Record<string, unknown> | null>(null);

  // --- گرید ---
  gridModuleKey = signal('');
  gridModuleName = signal('');
  gridRecords = signal<Record<string, unknown>[]>([]);
  gridLoading = signal(false);
  gridError = signal('');
  selectedRecord = signal<Record<string, unknown> | null>(null);

  // --- نمودار ماژول‌ها (+ آمار صفحه خانه) ---
  modules = signal<ModuleInfo[]>([]);
  stages = signal<StageInfo[]>([]);
  modulesLoading = signal(false);

  // درصد پر شدن توکن‌ها، برای نوار بالای صفحه
  tokenPercent(): number {
    if (this.maxTokens() === 0) return 0;
    return Math.min(100, Math.round((this.tokens() / this.maxTokens()) * 100));
  }

  // درصد پر شدن توکن‌ها در چت سرچ مقاله
  articleTokenPercent(): number {
    if (this.articleMaxTokens() === 0) return 0;
    return Math.min(100, Math.round((this.articleTokens() / this.articleMaxTokens()) * 100));
  }

  // تعداد رکورد یک ماژول، برای آمار صفحه خانه
  countForModule(moduleKey: string): number {
    return this.modules().find((m) => m.key === moduleKey)?.count ?? 0;
  }

  // آمار ماژول‌ها را از API تازه کن (صفحه خانه و نمودار ماژول‌ها)
  refreshModules() {
    this.api.getModules().subscribe({
      next: (res) => {
        this.modules.set(res.modules);
        this.stages.set(res.stages);
      },
      error: () => {
        // اگر API خاموش باشد، آمار صفر می‌ماند؛ خطا را در گاراژ/گرید نشان می‌دهیم
      },
    });
  }

  // --- گردونه سه‌بعدی صفحه خانه ---

  // یک قدم چرخش خودکار؛ وقتی موس روی صحنه است، درگ فعال است، یا نمای خانه
  // باز نیست، هیچ کاری نمی‌کند
  private autoTurntable() {
    if (this.turntablePaused() || this.dragStartX !== null || this.view() !== 'home') return;
    this.stepTurntable(this.turntableDirection);
  }

  // یک قدم به جلو یا عقب در لیست زاویه‌ها؛ در دو سر لیست جهت برمی‌گردد
  private stepTurntable(dir: 1 | -1) {
    const last = this.turntableImages.length - 1;
    let next = this.turntableIndex() + dir;
    if (next > last) { next = last - 1; this.turntableDirection = -1; }
    if (next < 0) { next = 1; this.turntableDirection = 1; }
    this.turntableIndex.set(next);
  }

  // فلش بعدی — دستی دور می‌زند تا کاربر هر وقت خواست بچرخاند
  turntableNext() {
    this.turntableDirection = 1;
    this.turntableIndex.set((this.turntableIndex() + 1) % this.turntableImages.length);
  }

  // فلش قبلی
  turntablePrev() {
    this.turntableDirection = -1;
    const n = this.turntableImages.length;
    this.turntableIndex.set((this.turntableIndex() - 1 + n) % n);
  }

  // پرش به یک زاویه با کلیک روی نقطه
  goToTurntableAngle(index: number) {
    this.turntableIndex.set(index);
  }

  // مکث چرخش خودکار وقتی موس روی صحنه است
  pauseTurntable() {
    this.turntablePaused.set(true);
  }

  resumeTurntable() {
    this.turntablePaused.set(false);
  }

  // شیب سه‌بعدی ملایم قاب عکس، بر اساس زاویه فعلی — تاب خوردن آرام، نه چرخش کامل
  turntableTilt(): string {
    const middle = (this.turntableImages.length - 1) / 2;
    const tiltY = (this.turntableIndex() - middle) * 1.6;
    return `rotateX(2deg) rotateY(${tiltY}deg)`;
  }

  // --- درگ دستی: کشیدن چپ/راست روی صحنه، زاویه را عوض می‌کند ---
  onTurntableDragStart(event: PointerEvent) {
    this.dragStartX = event.clientX;
    (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
  }

  onTurntableDragMove(event: PointerEvent) {
    if (this.dragStartX === null) return;
    const dx = event.clientX - this.dragStartX;
    if (Math.abs(dx) < 48) return;
    if (dx < 0) this.turntableNext(); else this.turntablePrev();
    this.dragStartX = event.clientX;
  }

  onTurntableDragEnd() {
    this.dragStartX = null;
  }

  send() {
    const text = this.input().trim();
    if (!text || this.loading()) return;

    this.messages.update((list) => [...list, { role: 'user', text }]);
    this.input.set('');
    this.loading.set(true);

    this.api.send(text, this.sessionId).subscribe({
      next: (res) => {
        this.sessionId = res.session_id;
        this.tokens.set(res.tokens);
        this.maxTokens.set(res.max_tokens);
        this.messages.update((list) => [
          ...list,
          { role: 'bot', text: res.reply, usedTool: res.used_tool },
        ]);
        // اگر درخواست تعمیراتی آماده شده باشد، مودال تایید را باز کن
        if (res.pending_confirmation) {
          this.confirmationSessionId = res.session_id;
          this.pendingConfirmation.set(res.pending_confirmation);
        }
        this.loading.set(false);
      },
      error: () => {
        this.messages.update((list) => [
          ...list,
          { role: 'bot', text: 'خطا: اول API پایتون را اجرا کن: python -m uvicorn api:app --reload --port 8000' },
        ]);
        this.loading.set(false);
      },
    });
  }

  // ارسال پیام در چت سرچ مقاله — مثل send ولی با جلسه و لیست پیام جدا
  sendArticle() {
    const text = this.articleInput().trim();
    if (!text || this.articleLoading()) return;

    this.articleMessages.update((list) => [...list, { role: 'user', text }]);
    this.articleInput.set('');
    this.articleLoading.set(true);

    this.api.send(text, this.articleSessionId).subscribe({
      next: (res) => {
        this.articleSessionId = res.session_id;
        this.articleTokens.set(res.tokens);
        this.articleMaxTokens.set(res.max_tokens);
        this.articleMessages.update((list) => [
          ...list,
          { role: 'bot', text: res.reply, usedTool: res.used_tool },
        ]);
        // مودال تایید مثل چت اصلی کار می‌کند
        if (res.pending_confirmation) {
          this.confirmationSessionId = res.session_id;
          this.pendingConfirmation.set(res.pending_confirmation);
        }
        this.articleLoading.set(false);
      },
      error: () => {
        this.articleMessages.update((list) => [
          ...list,
          { role: 'bot', text: 'خطا: اول API پایتون را اجرا کن: python -m uvicorn api:app --reload --port 8000' },
        ]);
        this.articleLoading.set(false);
      },
    });
  }

  // --- ناوبری تب‌ها ---
  goHome() {
    this.view.set('home');
    this.refreshModules();
  }

  goChat() {
    this.view.set('chat');
  }

  // سرچ مقاله: نمای جدا با هیستوری جدا، نه چت اصلی
  startArticleSearch() {
    this.view.set('articles');
  }

  // --- گاراژ ---
  openGarage() {
    this.view.set('garage');
    this.loadGarage();
  }

  // همه رکوردها را یکجا بگیر؛ داده کوچک و در حافظه است، فیلتر با پلاک سمت کلاینت است
  loadGarage() {
    this.garageLoading.set(true);
    this.garageError.set('');
    forkJoin({
      equipment: this.api.getRecords('equipment'),
      inspections: this.api.getRecords('inspections'),
      evaluations: this.api.getRecords('evaluations'),
      faults: this.api.getRecords('faults'),
      requests: this.api.getRecords('requests'),
      work_orders: this.api.getRecords('work_orders'),
    }).subscribe({
      next: (res) => {
        const all: Record<string, Record<string, unknown>[]> = {};
        for (const [key, value] of Object.entries(res)) all[key] = value.records;
        this.garageRecords.set(all);
        this.garageLoading.set(false);
      },
      error: () => {
        this.garageError.set('خطا: اول API پایتون را اجرا کن.');
        this.garageLoading.set(false);
      },
    });
  }

  // لیست تجهیزها برای کارت‌های گاراژ
  vehicles(): Record<string, unknown>[] {
    return this.garageRecords()['equipment'] ?? [];
  }

  // عکس خودرو بر اساس نام ثبت‌شده؛ فایل‌ها در frontend/public هستند
  // سمند → samand.jpg ، پراید → pride.jpg ، تارا → tara.jpg ، دنا → dena-plus.jpg
  // پژو پارس/پرشیا و هر نام دیگر → pars.jpg (پیش‌فرض)
  // تطابق زیررشته است، پس «سمند LX» و «تارا V4» هم درست شناخته می‌شوند
  carImageFor(name: string): string {
    const n = (name ?? '').trim().toLowerCase();
    if (n.includes('سمند') || n.includes('samand')) return '/samand.jpg';
    if (n.includes('پراید') || n.includes('pride')) return '/pride.jpg';
    if (n.includes('تارا') || n.includes('tara')) return '/tara.jpg';
    if (n.includes('دنا') || n.includes('dena')) return '/dena-plus.jpg';
    return '/pars.jpg';
  }

  // اگر فایل عکس نبود، پارس را نشان بده؛ اگر آن هم نبود، عکس را مخفی کن
  // تا هیچ‌وقت تصویر خراب دیده نشود
  onCarImageError(event: Event) {
    const img = event.target as HTMLImageElement;
    if (!img.src.endsWith('/pars.jpg')) {
      img.src = '/pars.jpg';
    } else {
      img.style.display = 'none';
    }
  }

  // رکوردهای یک ماژول برای یک پلاک مشخص
  private recordsForPlate(moduleKey: string, plate: string): Record<string, unknown>[] {
    return (this.garageRecords()[moduleKey] ?? []).filter((r) => r['plate'] === plate);
  }

  // مرحله فعلی یک خودرو — همان منطق current_stage در workflow.py، سمت کلاینت
  stageForPlate(plate: string): { key: string; name: string } {
    const inspections = this.recordsForPlate('inspections', plate);
    if (inspections.length === 0) return { key: 'inspection', name: 'ثبت بازدید' };
    const evaluations = this.recordsForPlate('evaluations', plate);
    if (evaluations.length === 0) return { key: 'evaluation', name: 'ثبت ارزیابی' };
    const faults = this.recordsForPlate('faults', plate);
    const requests = this.recordsForPlate('requests', plate);
    if (faults.length === 0 && requests.length === 0) return { key: 'evaluation', name: 'ثبت ارزیابی' };
    if (faults.length > 0 && requests.length === 0) return { key: 'fault', name: 'ثبت خرابی' };
    const latest = requests[requests.length - 1];
    if (latest['status'] !== 'تایید شده') return { key: 'repair_request', name: 'ثبت درخواست تعمیراتی' };
    const orders = this.recordsForPlate('work_orders', plate);
    if (orders.length === 0) return { key: 'approval', name: 'تایید درخواست' };
    return { key: 'work_order', name: 'ثبت حکم کار' };
  }

  openVehicle(vehicle: Record<string, unknown>) {
    this.selectedVehicle.set(vehicle);
  }

  closeVehicle() {
    this.selectedVehicle.set(null);
  }

  // گروه‌های سوابق خودروی انتخاب‌شده، برای مودال گاراژ
  vehicleGroups(): VehicleRecordGroup[] {
    const vehicle = this.selectedVehicle();
    if (!vehicle) return [];
    const plate = String(vehicle['plate'] ?? '');
    return VEHICLE_GROUPS.map((group) => ({
      key: group.key,
      label: group.label,
      items: this.recordsForPlate(group.key, plate).map((r) => ({
        tracking: String(r['tracking'] ?? ''),
        line: group.line(r),
      })),
    }));
  }

  // --- ثبت با چت، از گاراژ: هیچ فرمی نیست؛ فقط به چت‌بات می‌رویم با پیام آماده ---
  askChat(text: string) {
    this.closeVehicle();
    this.input.set(text);
    this.view.set('chat');
  }

  // اضافه کردن تجهیز — از گاراژ، با پیام آماده در چت‌بات
  addEquipment() {
    this.askChat('یک خودروی [نام خودرو] با پلاک [پلاک] ثبت کن');
  }

  // بازدید و ارزیابی یک فرایند است؛ یک دکمه برای هر دو، با پیام آماده در چت‌بات
  registerInspectionAndEvaluationFor(plate: string) {
    this.askChat(`برای خودروی با پلاک ${plate} بازدید و ارزیابی ثبت کن`);
  }

  registerFaultFor(plate: string) {
    this.askChat(`برای خودروی با پلاک ${plate} خرابی ثبت کن: [شرح خرابی را اینجا بنویس]`);
  }

  // تایید یا رد درخواست تعمیراتی از مودال؛ نتیجه به‌صورت پیام چت اضافه می‌شود
  // یک بار تایید کافی است؛ بک‌اند نتیجه را به جلسه چت اضافه می‌کند تا مدل دوباره نپرسد
  confirmRepairRequest(confirmed: boolean) {
    const pending = this.pendingConfirmation();
    if (!pending || this.confirming()) return;

    this.confirming.set(true);
    this.api.confirmRepairRequest(pending.confirmation_id, confirmed, this.confirmationSessionId).subscribe({
      next: (res) => {
        this.addConfirmationResult(res.message);
        this.pendingConfirmation.set(null);
        this.confirmationSessionId = null;
        this.confirming.set(false);
      },
      error: () => {
        this.addConfirmationResult('خطا: نتوانستم تایید را ثبت کنم؛ API پایتون را چک کن.');
        this.pendingConfirmation.set(null);
        this.confirmationSessionId = null;
        this.confirming.set(false);
      },
    });
  }

  // نتیجه تایید را به همان چتی اضافه کن که تاییدیه از آن آمده بود
  private addConfirmationResult(text: string) {
    if (this.confirmationSessionId !== null && this.confirmationSessionId === this.articleSessionId) {
      this.articleMessages.update((list) => [...list, { role: 'bot', text }]);
    } else {
      this.messages.update((list) => [...list, { role: 'bot', text }]);
    }
  }

  // کلاس بج وضعیت، بر اساس مقدار فیلد status
  statusClass(value: unknown): string {
    if (value === 'تایید شده') return 'badge badge-ok';
    if (value === 'در انتظار تایید') return 'badge badge-wait';
    return 'badge badge-info';
  }

  openGrid(moduleKey: string) {
    this.gridModuleKey.set(moduleKey);
    this.gridModuleName.set('');
    this.gridRecords.set([]);
    this.selectedRecord.set(null);
    this.gridError.set('');
    this.gridLoading.set(true);
    this.view.set('grid');
    this.api.getRecords(moduleKey).subscribe({
      next: (res) => {
        this.gridModuleName.set(res.name);
        this.gridRecords.set(res.records);
        this.gridLoading.set(false);
      },
      error: () => {
        this.gridError.set('خطا: اول API پایتون را اجرا کن.');
        this.gridLoading.set(false);
      },
    });
  }

  openModules() {
    this.modulesLoading.set(true);
    this.view.set('modules');
    this.api.getModules().subscribe({
      next: (res) => {
        this.modules.set(res.modules);
        this.stages.set(res.stages);
        this.modulesLoading.set(false);
      },
      error: () => {
        this.modulesLoading.set(false);
      },
    });
  }

  // ستون‌های گرید فعلی
  gridColumns(): { key: string; label: string }[] {
    return COLUMNS[this.gridModuleKey()] ?? [];
  }

  // فیلدهای رکورد انتخاب‌شده، برای پنل جزئیات
  detailEntries(): { label: string; value: string }[] {
    const rec = this.selectedRecord();
    if (!rec) return [];
    return Object.entries(rec).map(([key, value]) => ({
      label: FIELD_LABELS[key] ?? key,
      value: String(value ?? ''),
    }));
  }

  selectRecord(rec: Record<string, unknown>) {
    this.selectedRecord.set(rec);
  }

  closeDetail() {
    this.selectedRecord.set(null);
  }

  // تعداد رکورد یک مرحله، برای نمودار ماژول‌ها
  countForStage(stageKey: string): number {
    const moduleKey = STAGE_MODULE[stageKey];
    return this.modules().find((m) => m.key === moduleKey)?.count ?? 0;
  }

  // کلیک روی یک مرحله در نمودار → گرید همان ماژول
  openStageModule(stageKey: string) {
    this.openGrid(STAGE_MODULE[stageKey]);
  }
}
