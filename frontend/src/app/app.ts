import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService, ModuleInfo, PendingConfirmation, StageInfo } from './api.service';

interface ChatMessage {
  role: 'user' | 'bot';
  text: string;
  usedTool?: boolean;
}

type View = 'chat' | 'articles' | 'grid' | 'modules';

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

@Component({
  selector: 'app-root',
  imports: [FormsModule],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App {
  private api = inject(ApiService);

  // --- نما: چت، گرید، یا نمودار ماژول‌ها ---
  view = signal<View>('chat');

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

  // --- گرید ---
  gridModuleKey = signal('');
  gridModuleName = signal('');
  gridRecords = signal<Record<string, unknown>[]>([]);
  gridLoading = signal(false);
  gridError = signal('');
  selectedRecord = signal<Record<string, unknown> | null>(null);

  // --- نمودار ماژول‌ها ---
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

  // --- ناوبری سایدبار ---
  goChat() {
    this.view.set('chat');
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

  // سرچ مقاله: نمای جدا با هیستوری جدا، نه چت اصلی
  startArticleSearch() {
    this.view.set('articles');
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
