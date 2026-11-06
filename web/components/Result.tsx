import { FIELDS } from "@/lib/profile";
import type { Answer, ChecklistItem, Route, Verdict } from "@/lib/types";
import { gloss, rangeText, verdictText } from "@/lib/verdict";

const fieldLabel = (name: string) => FIELDS.find((f) => f.name === name)?.label ?? name;

function Badge({ verdict, testid }: { verdict: Verdict | null; testid?: string }) {
  return (
    <span className={`badge v-${verdict ?? "NONE"}`} data-testid={testid}>
      {verdictText(verdict)}
    </span>
  );
}

function RouteRow({ r }: { r: Route }) {
  return (
    <tr data-testid="route-row" data-route-key={r.key}>
      <td>{r.name}</td>
      <td>
        <Badge verdict={r.verdict} testid="route-verdict" />
      </td>
      <td>{gloss(r.verdict)}</td>
    </tr>
  );
}

function Item({ item }: { item: ChecklistItem }) {
  return (
    <article className="item" data-testid="checklist-item">
      <h4>
        <span className="axis">{item.axis_name}</span> <Badge verdict={item.verdict} />
      </h4>
      <p className="query">질의: {item.query}</p>
      {item.error && <p className="error">오류: {item.error}</p>}
      <p>{item.reason}</p>
      {item.note && <p className="note">{item.note}</p>}
      {item.conditions.length > 0 && (
        <>
          <p className="label">조건</p>
          <ul>
            {item.conditions.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </>
      )}
      {item.need_info.length > 0 && (
        <>
          <p className="label">필요한 정보</p>
          <ul>
            {item.need_info.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </>
      )}
      {item.outside.length > 0 && (
        <p className="hint">이유에서 언급했지만 이 질의의 검색 결과에는 없던 근거: {item.outside.join(", ")}</p>
      )}
      {item.citations.length > 0 && (
        <details>
          <summary>근거 {item.citations.length}개</summary>
          {item.citations.map((c) => (
            <div className="evidence" key={c.label}>
              <p>
                <strong>
                  {c.label} {c.title}
                </strong>
              </p>
              <p className="hint">
                {c.source}
                {c.url && (
                  <>
                    {" · "}
                    <a href={c.url} target="_blank" rel="noopener noreferrer">
                      원문 링크
                    </a>
                  </>
                )}
              </p>
              <pre>{c.text}</pre>
            </div>
          ))}
        </details>
      )}
    </article>
  );
}

export default function Result({ answer }: { answer: Answer }) {
  const missing = answer.score.missing ?? [];
  return (
    <section aria-labelledby="result-title" className="result">
      <h2 id="result-title">판정 결과</h2>
      <p className="global">
        전역 판정(일반공급): <strong data-testid="verdict-global">{verdictText(answer.verdict)}</strong>
      </p>
      <p className="hint">{gloss(answer.verdict)}</p>
      <p className="hint">
        공고일 {answer.as_of} 기준
        {answer.law_effective_date ? ` · 법령 시행일 ${answer.law_effective_date}` : ""}
      </p>
      {answer.trace_error && <p className="hint">질의 기록은 남기지 못했지만 판정은 위와 같습니다.</p>}

      <h3>신청 가능한 경로</h3>
      {answer.applicable.length === 0 ? (
        <p>없음</p>
      ) : (
        <ul>
          {answer.applicable.map((r) => (
            <li key={r.key}>
              {r.name} ({verdictText(r.verdict)})
            </li>
          ))}
        </ul>
      )}

      <h3>경로별 판정</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>경로</th>
              <th>판정</th>
              <th>뜻</th>
            </tr>
          </thead>
          <tbody>
            <RouteRow r={answer.general} />
            {answer.special.map((r) => (
              <RouteRow key={r.key} r={r} />
            ))}
          </tbody>
        </table>
      </div>

      <h3>가점 범위</h3>
      <p>
        총점 <strong>{rangeText(answer.score.total)}</strong>
        <span className="hint">
          {" "}
          (무주택 {rangeText(answer.score.homeless)} · 부양가족 {rangeText(answer.score.dependents)} ·
          통장 {rangeText(answer.score.savings)})
        </span>
      </p>
      {missing.length > 0 && (
        <p className="hint">빠진 입력: {missing.map(fieldLabel).join(", ")}</p>
      )}

      <h3>체크리스트 {answer.checklist.length}개</h3>
      {answer.checklist.map((item, i) => (
        <Item key={i} item={item} />
      ))}
    </section>
  );
}
