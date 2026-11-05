"use client";

import { useEffect, useState } from "react";
import { FIELDS, loadState, saveState, toPayload, type FormState } from "@/lib/profile";
import type { Answer } from "@/lib/types";
import Result from "./Result";

type Status =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "done"; answer: Answer };

function errorMessage(status: number, detail: string): string {
  if (status === 422) return `입력 값을 확인해 주세요. ${detail}`;
  if (status === 404) return "이 공고를 찾을 수 없습니다.";
  if (status === 503) return `판정 서비스를 지금 쓸 수 없습니다. 잠시 뒤에 다시 시도해 주세요. (${detail})`;
  if (status === 502) return "판정 서버에 연결하지 못했습니다. 잠시 뒤에 다시 시도해 주세요.";
  return `판정 중 오류가 났습니다. (${status}) ${detail}`;
}

export default function VerdictForm({ houseManageNo }: { houseManageNo: string }) {
  const [values, setValues] = useState<FormState>({});
  const [ready, setReady] = useState(false);
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  useEffect(() => {
    setValues(loadState());
    setReady(true);
  }, []);

  function change(name: string, value: string) {
    const next = { ...values, [name]: value };
    setValues(next);
    saveState(next);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setStatus({ kind: "loading" });
    try {
      const res = await fetch(`/api/verdict/${encodeURIComponent(houseManageNo)}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(toPayload(values)),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = typeof body.detail === "string" ? body.detail : "";
        setStatus({ kind: "error", message: errorMessage(res.status, detail) });
        return;
      }
      setStatus({ kind: "done", answer: body as Answer });
    } catch {
      setStatus({ kind: "error", message: errorMessage(502, "") });
    }
  }

  const loading = status.kind === "loading";
  return (
    <>
      <form onSubmit={submit} data-ready={ready ? "true" : "false"} data-testid="profile-form">
        <p className="hint">모르는 칸은 비워 두세요. 입력은 이 탭에만 남습니다. 원본 프로필은 서버에 저장하지 않고, 판정 기록에는 프로필의 해시와 판정 결과가 남습니다.</p>
        <div className="fields">
          {FIELDS.map((f) => (
            <label key={f.name}>
              <span>{f.label}</span>
              {f.kind === "bool" ? (
                <select
                  name={f.name}
                  value={values[f.name] ?? ""}
                  onChange={(e) => change(f.name, e.target.value)}
                >
                  <option value="">모름</option>
                  <option value="true">예</option>
                  <option value="false">아니오</option>
                </select>
              ) : f.kind === "date" ? (
                <input
                  type="date"
                  name={f.name}
                  value={values[f.name] ?? ""}
                  onChange={(e) => change(f.name, e.target.value)}
                />
              ) : (
                <input
                  type="number"
                  name={f.name}
                  min={0}
                  step={1}
                  inputMode="numeric"
                  value={values[f.name] ?? ""}
                  onChange={(e) => change(f.name, e.target.value)}
                />
              )}
            </label>
          ))}
        </div>
        <button type="submit" disabled={loading || !ready}>
          {loading ? "판정 중" : "판정하기"}
        </button>
      </form>
      <div aria-live="polite">
        {loading && <p data-testid="loading">판정 중… 처음 묻는 조합은 오래 걸릴 수 있습니다.</p>}
        {status.kind === "error" && (
          <p role="alert" className="error" data-testid="error">
            {status.message}
          </p>
        )}
        {status.kind === "done" && <Result answer={status.answer} />}
      </div>
    </>
  );
}
