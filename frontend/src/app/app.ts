import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService, ModuleInfo, StageInfo } from './api.service';

interface ChatMessage {
  role: 'user' | 'bot';
  text: string;
  usedTool?: boolean;
}

type View = 'chat' | 'grid' | 'modules';

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

  // --- ناوبری سایدبار ---
  goChat() {
    this.view.set('chat');
  }

  // آیکن‌های عملیاتی: یک پیام آماده در چت می‌گذارند، فرم ندارند
  startArticleSearch() {
    this.input.set('مقاله درباره نگهداری موتور خودرو پیدا کن');
    this.view.set('chat');
  }

  startEvaluation() {
    this.input.set('برای خودروی با پلاک ... ارزیابی ثبت کن');
    this.view.set('chat');
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
