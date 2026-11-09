"""로컬 DB의 공고·법령·청크를 배포 DB(Neon)로 옮긴다 (#85).

python -m cheongyak_rag.deploy_load --target-url <postgresql://...>

순서: ① 대상에 `alembic upgrade head` ② 로컬 컨테이너에서 `pg_dump --data-only`로 옮길 테이블만 뽑아
③ 컨테이너의 `psql`로 대상에 넣는다 ④ 테이블마다 행 수를 원본·대상에서 세어 표로 찍는다.
하나라도 다르면 0이 아닌 코드로 끝낸다.

- 로컬 `psql`은 14라 pg17 서버를 못 덤프한다.
  덤프와 적재 둘 다 `docker exec cheongyak-db`(pg17)로 한다
- 원본은 읽기만 한다. 대상이 원본과 같은 호스트·DB 이름이면 거부한다
- 대상 URL은 출력에 찍지 않는다(호스트만 찍는다). `psql`에도 인자가 아니라 환경 변수로 넘긴다
- `traces`(로컬 측정 기록)·`verdict_daily_count`(하루 판정 한도)·`alembic_version`은 옮기지 않는다
"""

import argparse
import os
import re
import subprocess
import sys
from collections.abc import Callable

import sqlalchemy as sa
from sqlalchemy.engine import URL, make_url

from cheongyak_rag.config import REPO, settings

CONTAINER = "cheongyak-db"
EXCLUDED = frozenset({"traces", "verdict_daily_count", "alembic_version"})
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "host.docker.internal", ""}
_SAFE_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")


class LoadError(Exception):
    """대상이나 환경이 옮기기에 맞지 않다. 메시지에 URL·비밀을 넣지 않는다."""


def normalize(url: str) -> URL:
    """설정과 같은 규칙으로 `postgres://`·`postgresql://`를 psycopg 꼴로 읽는다."""
    for old in ("postgres://", "postgresql://"):
        if url.startswith(old):
            url = "postgresql+psycopg://" + url[len(old) :]
    return make_url(url)


def to_libpq(url: URL) -> str:
    """`psql`이 읽는 `postgresql://` 꼴. 비밀번호를 포함하므로 출력하지 않는다."""
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


def container_url(url: URL) -> URL:
    """컨테이너 안에서 보는 주소. 호스트의 localhost는 컨테이너에서 `host.docker.internal`이다."""
    if (url.host or "") in LOCAL_HOSTS:
        return url.set(host="host.docker.internal")
    return url


def same_database(a: URL, b: URL) -> bool:
    def host(u: URL) -> str:
        h = (u.host or "").lower()
        return "local" if h in LOCAL_HOSTS else h

    return host(a) == host(b) and a.database == b.database


def redact(text: str, url: URL) -> str:
    for secret in (url.password, to_libpq(url)):
        if secret:
            text = text.replace(secret, "***")
    return text


def movable_tables(engine: sa.Engine) -> list[str]:
    """원본 `public` 스키마의 테이블에서 옮기지 않는 것을 뺀 목록. 코드에 목록을 고정하지 않는다."""
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT table_name FROM information_schema.tables"
                " WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY table_name"
            )
        )
        names = [r[0] for r in rows]
    tables = [n for n in names if n not in EXCLUDED]
    bad = [n for n in tables if not _SAFE_NAME.match(n)]
    if bad:
        raise LoadError(f"테이블 이름을 덤프 인자로 쓸 수 없다: {bad}")
    return tables


def count_rows(engine: sa.Engine, tables: list[str]) -> dict[str, int]:
    with engine.connect() as conn:
        return {
            t: conn.execute(sa.text(f'SELECT count(*) FROM "{t}"')).scalar_one() for t in tables
        }


def compare(source: dict[str, int], target: dict[str, int]) -> tuple[list[str], bool]:
    """행 수 표(줄 목록)와 전부 같은지."""
    width = max((len(t) for t in source), default=5)
    lines = [f"{'테이블'.ljust(width)}  {'원본':>8}  {'대상':>8}  결과"]
    ok = True
    for t, n in source.items():
        m = target.get(t)
        same = m == n
        ok &= same
        got = "-" if m is None else m
        verdict = "같다" if same else "다르다"
        lines.append(f"{t.ljust(width)}  {n:>8}  {got:>8}  {verdict}")
    return lines, ok


def upgrade_target(target: URL) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO,
        env={**os.environ, "DATABASE_URL": target.render_as_string(hide_password=False)},
        capture_output=True,
        text=True,
    )
    if proc.returncode:
        raise LoadError("대상에 alembic upgrade head 실패:\n" + redact(proc.stderr[-2000:], target))


def copy_data(source: URL, target: URL, tables: list[str], container: str = CONTAINER) -> None:
    """원본 컨테이너에서 덤프해 같은 컨테이너의 psql로 대상에 한 트랜잭션으로 넣는다."""
    dump_cmd = ["docker", "exec", container, "pg_dump", "--data-only", "--no-owner"]
    dump_cmd += ["-U", source.username or "postgres", "-d", source.database or "postgres"]
    for t in tables:
        dump_cmd += ["-t", f"public.{t}"]
    # URL은 인자로 넘기면 프로세스 목록에 보인다. 환경 변수로 넘겨 컨테이너 안에서 펼친다
    load_cmd = [
        "docker", "exec", "-i", "-e", "TARGET_URL", container,
        "sh", "-c", 'exec psql "$TARGET_URL" -q -v ON_ERROR_STOP=1 --single-transaction',
    ]  # fmt: skip
    env = {**os.environ, "TARGET_URL": to_libpq(container_url(target))}
    dump = subprocess.Popen(dump_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    load = subprocess.Popen(
        load_cmd, stdin=dump.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env
    )
    assert dump.stdout is not None
    dump.stdout.close()  # psql이 먼저 끝나면 pg_dump가 SIGPIPE를 받게 한다
    _, load_err = load.communicate()
    dump_err = dump.stderr.read() if dump.stderr else b""
    dump.wait()
    # psql이 먼저 죽으면 pg_dump는 파이프가 끊겨 따라 죽는다 — 원인인 psql 쪽을 먼저 보여 준다
    if load.returncode:
        raise LoadError(
            "psql 적재 실패 (한 트랜잭션이라 대상에는 아무것도 안 들어갔다):\n"
            + redact(load_err.decode(errors="replace")[-2000:], target)
        )
    if dump.returncode:
        raise LoadError(
            "pg_dump 실패. 일부가 들어갔을 수 있으니 대상을 비우고 다시 해야 한다:\n"
            + redact(dump_err.decode(errors="replace")[-2000:], target)
        )


def run(
    target_url: str,
    source_url: str | None = None,
    out: Callable[[str], None] = print,
) -> int:
    source = normalize(source_url or settings.database_url)
    target = normalize(target_url)
    if same_database(source, target):
        out("대상이 원본과 같은 호스트·DB 이름이다. 원본을 덮어쓰지 않으려고 거부한다")
        return 1
    out(f"원본: {source.host}/{source.database}  →  대상 호스트: {target.host}")
    src_engine = sa.create_engine(source)
    tgt_engine = sa.create_engine(target)
    try:
        tables = movable_tables(src_engine)
        out(f"옮길 테이블 {len(tables)}개: {', '.join(tables)}")
        out("① 대상에 alembic upgrade head")
        upgrade_target(target)
        before = count_rows(tgt_engine, tables)
        filled = {t: n for t, n in before.items() if n}
        if filled:
            out(f"대상에 이미 행이 있다 {filled}. 두 번 넣으면 행이 불어나서 거부한다")
            return 1
        out("②③ pg_dump → psql (한 트랜잭션)")
        copy_data(source, target, tables)
        lines, ok = compare(count_rows(src_engine, tables), count_rows(tgt_engine, tables))
        out("④ 행 수 대조")
        for line in lines:
            out(line)
        out("전부 같다" if ok else "행 수가 다른 테이블이 있다")
        return 0 if ok else 1
    except LoadError as e:
        out(str(e))
        return 1
    finally:
        src_engine.dispose()
        tgt_engine.dispose()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="deploy_load", description=__doc__.split("\n")[0])
    ap.add_argument("--target-url", required=True, help="배포 DB 주소 (postgresql://...)")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    return run(args.target_url)


if __name__ == "__main__":
    sys.exit(main())
