"""Вердикт принадлежит голове (Статья 60).

Законы, обеспеченные этим кодом:
    60.1 вердикт привязан к SHA головы, а не к моменту: успех на другой
        голове вердиктом не считается.
    60.2 отменённый прогон — НЕ зелёный: отмена не публикует ни артефактов,
        ни результатов; молчание — это «нет вердикта», а не «успех».
    60.3 на главной ветке отмена ЗАПРЕЩЕНА: каждый коммит заслуживает своего
        результата (иначе не узнать, который из них сломал); отменяем только
        боковые прогоны (PR).
    60.4 удалённая голова — источник истины: вердикт головы дома считается
        только когда дом и сервер смотрят на один SHA (иначе дом судит копию).
    60.5 вердикт сверяется целиком: последний ЗАВЕРШЁННЫЙ прогон каждого
        контура; провал после успеха на той же голове краснит её.

Мировой опыт (разведка 01.10.2026: concurrency-правила GitHub Actions,
«cancelled publish neither artifacts nor test results»; «on main every commit
deserves its own result» — cancel only on PRs) — основание 60.2 и 60.3.

MODE: product
"""

from __future__ import annotations

import json
import subprocess
import urllib.request
from pathlib import Path

КОРЕНЬ = Path(__file__).parent.parent
РЕПО = "sergey1772/poligon"
API = "https://api.github.com"
ЗАВЕРШЁННЫЕ = ("success", "failure", "cancelled", "timed_out", "skipped",
               "neutral", "stale", "startup_failure", "action_required")
БЕЗ_ОТМЕНЫ = "refs/heads/main"


class НарушениеЗакона(Exception):
    """Попытка действия, запрещённого Конституцией."""


def голова_дома(дом: Path | None = None) -> str:
    """SHA головы дома (локальная копия)."""
    р = subprocess.run(["git", "-C", str(дом or КОРЕНЬ), "rev-parse", "HEAD"],
                       capture_output=True, text=True, timeout=30)
    return р.stdout.strip() if р.returncode == 0 else ""


def _голос_сервера(репо: str, ветка: str = "main") -> dict:
    """HTTP GET к GitHub с токеном из сейфа; без сейфа — честный отказ."""
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from выгрузка import токен_из_сейфа
        с = токен_из_сейфа()
        токен = с.get("токен")
    except Exception:                        # noqa: BLE001 — сейфа нет, это не падение
        токен = None
    if not токен:
        return {"отказ": "сейф: нет токена"}
    з = urllib.request.Request(
        f"{API}/repos/{репо}/commits/{ветка}",
        headers={"Authorization": "Bearer " + токен,
                 "User-Agent": "spurt-dom",
                 "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(з, timeout=20) as о:
            return json.loads(о.read().decode("utf-8"))
    except Exception as е:                   # noqa: BLE001 — сеть честно молчит
        return {"отказ": f"{type(е).__name__}"}


def голова_сервера(репо: str = РЕПО, ветка: str = "main") -> str:
    """SHA головы удалённого репозитория (источник истины, 60.4)."""
    ответ = _голос_сервера(репо, ветка)
    return str(ответ.get("sha") or "")


# ИМЕНА КОНТУРОВ — КОНТРАКТ (имя workflow из файла, ст. 58):
# у ворот name: «ворота», у полигона — латиница «poligon». Русское написание
# в списке контуров дало ложное «не запускался» живой пробой 01.10.
КОНТУРЫ_ДОМА = ("ворота", "poligon")


def из_прогонов(ша: str, прогоны: list[dict],
                контуры: tuple[str, ...] = ()) -> dict:
    """60.1/60.2/60.5: вердикт по прогонам ОДНОЙ головы.

    По каждому контуру берётся последний ЗАВЕРШЁННЫЙ прогон; отменённый не
    считается вердиктом; провал после успеха краснит. Прогоны чужих голов
    не влияют: вердикт принадлежит голове.
    """
    по_контуру: dict[str, dict] = {}
    for п in прогоны:
        if str(п.get("head_sha") or "") != ша:
            continue
        имя = str(п.get("name") or "?")
        был = по_контуру.get(имя)
        ключ = (int(п.get("run_number") or 0), str(п.get("created_at") or ""))
        ключ_был = ((int(был.get("run_number") or 0),
                     str(был.get("created_at") or "")) if был else None)
        if ключ_был is None or ключ > ключ_был:
            по_контуру[имя] = п
    вердикты: dict[str, str] = {}
    for имя, п in по_контуру.items():
        статус = str(п.get("status") or "")
        исход = str(п.get("conclusion") or "")
        if статус != "completed":
            вердикты[имя] = "идёт"
        elif исход == "cancelled":
            вердикты[имя] = "нет вердикта"       # 60.2: отмена — не успех
        elif исход in ЗАВЕРШЁННЫЕ:
            вердикты[имя] = "зелёный" if исход == "success" else "красный"
        else:
            вердикты[имя] = "нет вердикта"
    for имя in контуры:                    # 60.5: не судился — не зелёный
        вердикты.setdefault(имя, "не запускался")
    if not вердикты:
        общий = "нет прогонов"
    elif any(в == "красный" for в in вердикты.values()):
        общий = "красный"
    elif any(в in ("нет вердикта", "идёт", "не запускался")
             for в in вердикты.values()):
        общий = "нет вердикта"                   # ни зелёный, ни красный
    else:
        общий = "зелёный"
    return {"голова": ша, "вердикты": вердикты, "вердикт": общий,
            "контуров": len(вердикты)}


def свод(дом: Path | None = None, прогоны: list[dict] | None = None,
         голова_сервера_ша: str | None = None) -> dict:
    """Свод 60.4: дом и сервер смотрят на одну голову; вердикт — по ней."""
    дом = дом or КОРЕНЬ
    домашняя = голова_дома(дом)
    серверная = (голова_сервера_ша if голова_сервера_ша is not None
                 else голова_сервера())
    if прогоны is None:
        ответ = _голос_сервера(РЕПО, "main")
        прогоны = []
        if not ответ.get("отказ"):
            вр = _прогоны_api()
            прогоны = вр
    один_ша = bool(домашняя) and bool(серверная) and домашняя == серверная
    в = из_прогонов(домашняя, прогоны, КОНТУРЫ_ДОМА) if домашняя else {
        "голова": "", "вердикты": {}, "вердикт": "нет прогонов", "контуров": 0}
    состояния = {
        "одна_голова": один_ша,
        "вердикт": в["вердикт"],
        "причина": ("голова дома и сервера совпадают" if один_ша
                    else "дом судит копию: голова дома ≠ головы сервера"),
    }
    return {"дом": домашняя[:8], "сервер": (серверная or "?")[:8],
            "вердикты": в["вердикты"], **состояния}


def _прогоны_api(страниц: int = 2) -> list[dict]:
    """Последние прогоны репозитория (для свода дома)."""
    итог: list[dict] = []
    for стр in range(1, страниц + 1):
        ответ = _запрос(f"{API}/repos/{РЕПО}/actions/runs?per_page=50&page={стр}")
        if ответ.get("отказ"):
            break
        итог.extend(ответ.get("workflow_runs") or [])
    return итог


def _запрос(адрес: str) -> dict:
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from выгрузка import токен_из_сейфа
        токен = токен_из_сейфа().get("токен")
    except Exception:                        # noqa: BLE001
        токен = None
    if not токен:
        return {"отказ": "сейф: нет токена"}
    з = urllib.request.Request(адрес, headers={
        "Authorization": "Bearer " + токен, "User-Agent": "spurt-dom",
        "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(з, timeout=25) as о:
            return json.loads(о.read().decode("utf-8"))
    except Exception as е:                   # noqa: BLE001
        return {"отказ": f"{type(е).__name__}"}


def отмена_на_главной_запрещена(файл: Path) -> list[str]:
    """60.3: в контуре не должно быть отмены прогонов главной ветки."""
    з: list[str] = []
    текст = Path(файл).read_text(encoding="utf-8")
    if "cancel-in-progress: true" in текст:
        з.append("cancel-in-progress: true безусловно — на главной ветке "
                 "отмена запрещена (60.3); отменяем только боковые прогоны")
    return з


def главное(доводы: list[str] | None = None) -> int:
    """CLI: `вердикт.py` — свод по голове; `--файл Ф` — суд контура."""
    import sys
    доводы = доводы if доводы is not None else sys.argv[1:]
    if "--файл" in доводы:
        и = доводы.index("--файл")
        файл = Path(доводы[и + 1]) if и + 1 < len(доводы) else None
        if файл is None:
            print("вердикт: укажи файл контура")
            return 2
        з = отмена_на_главной_запрещена(файл)
        print(f"КОНТУР {файл.name}: " + ("чисто" if not з else "нарушения"))
        for с in з:
            print(f"  ⚠ {с}")
        return 0 if not з else 1
    с = свод()
    print(f"ВЕРДИКТ ГОЛОВЫ: дом {с['дом']} · сервер {с['сервер']} · "
          f"{с['вердикт']} · {с['причина']}")
    for к, в in sorted(с["вердикты"].items()):
        print(f"  {к}: {в}")
    return 0 if с["вердикт"] == "зелёный" and с["одна_голова"] else 1


if __name__ == "__main__":
    raise SystemExit(главное())
