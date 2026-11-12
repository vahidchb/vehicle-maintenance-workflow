import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface ChatReply {
  reply: string;
  session_id: string;
  tokens: number;
  max_tokens: number;
  used_tool: boolean;
  // اگر در این دور درخواست تعمیراتی آماده شده باشد، با این اطلاعات مودال تایید باز می‌شود
  pending_confirmation: PendingConfirmation | null;
}

// تاییدیه در انتظار درخواست تعمیراتی — همان چیزی که مودال نشان می‌دهد
export interface PendingConfirmation {
  confirmation_id: string;
  plate: string;
  equipment: string;
  evaluation_id: string;
  fault_id: string;
  fault: string;
  description: string;
}

export interface ConfirmResult {
  ok: boolean;
  tracking: string | null;
  message: string;
}

export interface ModuleInfo {
  key: string;
  name: string;
  count: number;
}

export interface StageInfo {
  key: string;
  name: string;
  prefix: string;
  description: string;
}

export interface ModulesResponse {
  modules: ModuleInfo[];
  stages: StageInfo[];
}

export interface RecordsResponse {
  module: string;
  name: string;
  records: Record<string, unknown>[];
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  private http = inject(HttpClient);
  // آدرس API پایتون (FastAPI روی پورت 8000)
  private base = 'http://localhost:8000/api';

  send(message: string, sessionId: string | null): Observable<ChatReply> {
    return this.http.post<ChatReply>(`${this.base}/chat`, {
      message,
      session_id: sessionId,
    });
  }

  // تایید یا رد درخواست تعمیراتی آماده‌شده (از مودال تایید)
  confirmRepairRequest(confirmationId: string, confirmed: boolean): Observable<ConfirmResult> {
    return this.http.post<ConfirmResult>(`${this.base}/confirm-repair-request`, {
      confirmation_id: confirmationId,
      confirmed,
    });
  }

  getModules(): Observable<ModulesResponse> {
    return this.http.get<ModulesResponse>(`${this.base}/modules`);
  }

  getRecords(moduleKey: string): Observable<RecordsResponse> {
    return this.http.get<RecordsResponse>(`${this.base}/records/${moduleKey}`);
  }
}
