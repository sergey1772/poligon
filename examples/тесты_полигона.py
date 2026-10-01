"""Тесты полигона (О-17): фотонность внутри обязательна — ни одна часть не
дольше 45 с, журнал переживает обрыв, фон останавливается стоп-файлом, а не
убийством, вскрытие называет упавших поимённо."""

# MODE: product

from __future__ import annotations

import json
import sys
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(КОРЕНЬ / "examples"))


def _клетка(tmp_path, мера: dict | None = None):
    (tmp_path / "examples").mkdir()
    (tmp_path / "00_START").mkdir()
    (tmp_path / "examples" / "тесты_м.py").write_text(
        "def test_раз():\n    assert True\n\n\ndef test_два():\n    assert True\n",
        encoding="utf-8")
    (tmp_path / "examples" / "тесты_н.py").write_text(
        "def test_три():\n    assert True\n", encoding="utf-8")
    (tmp_path / "00_START" / "время_тестов.json").write_text(json.dumps(
        мера or {"файлы": {"тесты_м.py": 20.0, "тесты_н.py": 20.0}},
        ensure_ascii=False), encoding="utf-8")
    return tmp_path


def test_план_дробен_и_покрывает_все_тесты(tmp_path):
    import полигон
    дом = _клетка(tmp_path)
    части = полигон.план(дом, бюджет_с=45)
    assert части, "плана нет"
    for ч in части:
        assert ч["секунд"] <= 45.0, ч
    покрытие = {str(ф).split("::")[0] for ч in части for ф in ч["файлы"]}
    assert покрытие == {"тесты_м.py", "тесты_н.py"}, покрытие


def test_часть_пишет_журнал_и_идемпотентна(tmp_path):
    import полигон
    дом = _клетка(tmp_path)
    полигон.начать(дом, бюджет_с=45)
    ок, хвост, сек = полигон.часть(дом, 1)
    assert ок, (хвост, сек)
    assert сек <= 45.0, сек
    ж = полигон.загрузить(дом)
    assert ж["части"][0]["статус"] == "ок", ж["части"][0]
    ок2, хвост2, сек2 = полигон.часть(дом, 1)      # второй раз — из журнала
    assert ок2 and "из журнала" in хвост2 and сек2 == 0.0, (хвост2, сек2)


def test_журнал_переживает_обрыв_и_продолжает(tmp_path):
    """Мера 30+30 при бюджете 45 даёт ДВЕ части: после первой следующая —
    вторая (обрыв процесса не откатывает сделанного)."""
    import полигон
    дом = _клетка(tmp_path, мера={"файлы": {"тесты_м.py": 30.0, "тесты_н.py": 30.0}})
    полигон.начать(дом, бюджет_с=45)
    полигон.часть(дом, 1)
    # «процесс упал»: новый вызов читает журнал на диске и идёт дальше
    ж = полигон.загрузить(дом)
    след = полигон.следующая(ж)
    assert след is not None and след["номер"] == 2, след


def test_вмерзание_пересобирает_план_мельче(tmp_path, monkeypatch):
    import полигон
    дом = _клетка(tmp_path, мера={"файлы": {"тесты_м.py": 40.0, "тесты_н.py": 5.0},
                                  "тесты": {"тесты_м.py::test_раз": 38.0,
                                            "тесты_м.py::test_два": 2.0}})
    полигон.начать(дом, бюджет_с=45)

    def мертвый_запуск(*a, **к):
        raise полигон.subprocess.TimeoutExpired(cmd="pytest", timeout=45)

    monkeypatch.setattr(полигон.subprocess, "run", мертвый_запуск)
    ок, хвост, _ = полигон.часть(дом, 1)
    assert ок is False and "ТАЙМАУТ" in хвост, хвост
    ж = полигон.загрузить(дом)
    assert ж["части"][0]["статус"] == "вмерзла", ж["части"][0]
    хвостовые = [ч for ч in ж["части"] if ч["номер"] > 1]
    assert хвостовые, "план не пересобран"
    единицы = [е for ч in хвостовые for е in ч["файлы"]]
    assert any(е.startswith("тесты_м.py::") for е in единицы), единицы


def test_фон_останавливается_стоп_файлом(tmp_path):
    import полигон
    дом = _клетка(tmp_path)
    полигон.начать(дом, бюджет_с=45)
    полигон.стоп(дом, почему="проба")
    итог = полигон.цикл(дом, минут=1.0, пауза_с=0.0)
    assert итог["шагов"] == 0, итог          # стоп-файл: ни одной части
    assert (дом / полигон.СТОП).exists()
    assert полигон.снять_стоп(дом) is True


def test_цикл_закрывает_план_частями(tmp_path):
    import полигон
    дом = _клетка(tmp_path)
    полигон.начать(дом, бюджет_с=45)
    итог = полигон.цикл(дом, минут=2.0, пауза_с=0.0)
    assert итог["состояние"] == "готов", итог
    assert итог["ок"] == итог["частей"] and итог["шагов"] >= 1, итог


def test_вскрытие_называет_упавших(tmp_path):
    import полигон
    дом = _клетка(tmp_path)
    (дом / "examples" / "тесты_плохой.py").write_text(
        "def test_падает():\n    assert False, 'нарочно'\n", encoding="utf-8")
    полигон.начать(дом, бюджет_с=45)
    ж = полигон.загрузить(дом)
    номер = next(ч["номер"] for ч in ж["части"]
                 if any("плохой" in ф for ф in ч["файлы"]))
    ок, _, _ = полигон.часть(дом, номер)
    assert ок is False
    в = полигон.вскрытие(дом)
    assert в["красных"] >= 1, в
    текст = (дом / полигон.ВСКРЫТИЕ).read_text(encoding="utf-8")
    assert "тесты_плохой.py::test_падает" in текст, текст[:400]


def test_статус_и_бюджет_у_сторожа(tmp_path):
    import полигон
    import сторож_песочницы as ст
    дом = _клетка(tmp_path)
    assert полигон.бюджет(дом) <= ст.ПРЕДЕЛ_ВЫЗОВА_С
    ст.вмерзание(дом, "часть", сек=70, предел=70)
    assert полигон.бюджет(дом) < ст.БЮДЖЕТ_ПОТОЛОК_С, полигон.бюджет(дом)
    полигон.начать(дом)
    с = полигон.статус(дом)
    assert с["частей"] >= 1 and с["бюджет_с"] == полигон.бюджет(дом), с



def test_план_для_матрицы_github_детерминирован(tmp_path, capsys):
    """План для CI — JSON: каждая часть матрицы знает свой номер и размер;
    тот же план должен получиться в любом отдельном раннере (детерминизм)."""
    import json as _j
    import полигон
    дом = _клетка(tmp_path)
    assert полигон.главное([str(дом), "--план-json"]) == 0
    п1 = _j.loads(capsys.readouterr().out)
    assert полигон.главное([str(дом), "--план-json"]) == 0
    п2 = _j.loads(capsys.readouterr().out)
    assert п1 == п2, (п1, п2)
    assert п1["всего"] >= 1 and all(ч["секунд"] <= 50 for ч in п1["части"]), п1
    assert all(ч["номер"] == н for н, ч in enumerate(п1["части"], 1)), п1


def test_часть_кладёт_артефакты_и_сводка_судит(tmp_path, capsys):
    """CI: часть кладёт junit и сайдкар в каталог артефактов; сводка по каталогу
    даёт вердикт и следит за Статьёй 56 (вызов >50 с — красное)."""
    import json as _j
    import полигон
    дом = _клетка(tmp_path)
    полигон.начать(дом, бюджет_с=45)
    арт = tmp_path / "артефакты"
    ок, _, сек = полигон.часть(дом, 1, куда=арт)
    assert ок, (сек,)
    assert (арт / "часть1.json").exists() and (арт / "часть1.xml").exists()
    assert полигон.главное([str(дом), "--сводка", str(арт)]) == 0, \
        capsys.readouterr().out
    (арт / "часть9.json").write_text(_j.dumps(
        {"номер": 9, "имя": "полигон-фотон 9/9", "файлы": ["тесты_м.py"],
         "секунд": 120.0, "статус": "ок", "хвост": "ok", "падений": []},
        ensure_ascii=False), encoding="utf-8")
    assert полигон.главное([str(дом), "--сводка", str(арт)]) == 1, "не поймал"
    вывод = capsys.readouterr().out
    assert "Статья 56" in вывод and "120" in вывод, вывод


def test_сводка_называет_упавших(tmp_path):
    import json as _j
    import полигон
    арт = tmp_path / "арт"
    арт.mkdir()
    (арт / "часть1.json").write_text(_j.dumps(
        {"номер": 1, "имя": "фотон 1/1", "файлы": ["тесты_м.py"], "секунд": 12.0,
         "статус": "провал", "хвост": "1 failed",
         "падений": ["тесты_м.py::test_два"]}, ensure_ascii=False),
        encoding="utf-8")
    с = полигон.сводка(арт)
    assert с["вердикт"] == "КРАСНЫЙ" and с["провалы"] == [1], с
    assert с["упавшие"] == ["тесты_м.py::test_два"], с



def test_клетка_ci_не_наследует_паузу_и_собирает_стандарт(tmp_path, monkeypatch):
    """GitHub-клетка: полигон сам снимает чужую паузу и собирает производное —
    иначе красное в CI будет про среду, а не про код (Статья 34.2)."""
    import json as _j
    import полигон
    дом = _клетка(tmp_path)
    (дом / "41_MECHANISMS").mkdir()
    (дом / "examples" / "стоп.py").write_text(
        (Path(полигон.__file__).parent / "стоп.py").read_text(encoding="utf-8"),
        encoding="utf-8")
    (дом / "41_MECHANISMS" / "стоп_контур.json").write_text(_j.dumps(
        {"пауза": [["семья", ""]], "журнал": [], "агенты": []},
        ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    отчёт = полигон.подготовить_клетку(дом)
    assert отчёт["клетка"] is True, отчёт
    assert отчёт["пауза_снята"] is True, отчёт
    состояние = _j.loads((дом / "41_MECHANISMS" / "стоп_контур.json")
                         .read_text(encoding="utf-8"))
    assert состояние["пауза"] == [], состояние
    assert отчёт["стандарт"] in ("есть", "собран", "не собран"), отчёт


def test_клетка_готова_не_трогает_живой_дом(tmp_path, monkeypatch):
    """Дома (не в CI) полигон ничего не снимает: пауза Суверена священна."""
    import полигон
    дом = _клетка(tmp_path)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    отчёт = полигон.подготовить_клетку(дом)
    assert отчёт["клетка"] is False and отчёт["пауза_снята"] is False, отчёт



def test_суд_дрожи_снимает_случайное_красное(tmp_path, monkeypatch):
    """Дрожь (случайное красное) не смеет краснить дом: повтор ровно упавших
    узлов зелёный → часть закрыта, а дрожь названа в журнале."""
    import полигон
    дом = _клетка(tmp_path)
    полигон.начать(дом, бюджет_с=45)
    зов = {"н": 0}

    class Итог:
        def __init__(self, код, вывод):
            self.returncode, self.stdout, self.stderr = код, вывод, ""

    xml_плохой = ("<testsuites><testsuite name='pytest'>"
                  "<testcase classname='examples.тесты_м' file='examples/тесты_м.py'"
                  " name='test_раз' time='0.1'><failure message='дрожь'>x</failure>"
                  "</testcase></testsuite></testsuites>")

    def фальшивый_запуск(команда, **к):
        зов["н"] += 1
        if зов["н"] == 1:                     # первый прогон: красное
            for арг in команда:
                if str(арг).startswith("--junit-xml="):
                    Path(str(арг).split("=", 1)[1]).write_text(xml_плохой,
                                                               encoding="utf-8")
            return Итог(1, "1 failed in 0.3s\n")
        return Итог(0, "1 passed in 0.2s\n")   # повтор: зелёное

    monkeypatch.setattr(полигон.subprocess, "run", фальшивый_запуск)
    ок, хвост, _ = полигон.часть(дом, 1)
    assert ок is True, (хвост,)
    assert "дрожь снята повтором" in хвост, хвост
    ж = полигон.загрузить(дом)
    ч = ж["части"][0]
    assert ч["статус"] == "ок" and ч["падений"] == [] and ч["дрожь"], ч


def test_plan_json_stdout_чист_в_клетке_ci(tmp_path, monkeypatch):
    """Контракт CI: stdout `--plan-json` — только JSON (логи — в stderr),
    иначе раннер GitHub падает на json.load — так и было в прогоне 36739211636."""
    import io
    import json as _j
    from contextlib import redirect_stdout
    import полигон
    дом = _клетка(tmp_path)
    (дом / "41_MECHANISMS").mkdir()
    (дом / "examples" / "стоп.py").write_text(
        (Path(полигон.__file__).parent / "стоп.py").read_text(encoding="utf-8"),
        encoding="utf-8")
    (дом / "41_MECHANISMS" / "стоп_контур.json").write_text(_j.dumps(
        {"пауза": [["семья", ""]], "журнал": [], "агенты": []},
        ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    буфер = io.StringIO()
    with redirect_stdout(буфер):
        код = полигон.главное([str(дом), "--plan-json"])
    план = _j.loads(буфер.getvalue())          # бросит, если stdout не чист
    assert код == 0 and план["total"] >= 1 and план["parts"], план


def test_пропуск_из_журнала_оставляет_улику_в_ci(tmp_path):
    """Идемпотентный пропуск не смеет скрывать часть от сводки CI: улика
    (сайдкар) пишется и тогда, когда мера взята из журнала."""
    import json as _j
    import полигон
    дом = _клетка(tmp_path)
    полигон.начать(дом, бюджет_с=45)
    полигон.часть(дом, 1)
    арт = tmp_path / "арт"
    ок, хвост, _ = полигон.часть(дом, 1, куда=арт)   # второй раз: из журнала
    assert ок and "из журнала" in хвост, (хвост,)
    д = _j.loads((арт / "часть1.json").read_text(encoding="utf-8"))
    assert д["part"] == 1 and д["status"] == "ok", д


def test_сводка_ci_краснеет_на_неполном_прогоне(tmp_path):
    """«3 части из 6» — не победа: сводка сверяется с планом и краснеет,
    иначе зелёное врёт (прогон 36739489358: PROD-READY при parts 3)."""
    import json as _j
    import полигон
    арт = tmp_path / "арт"
    арт.mkdir()
    (арт / "plan.json").write_text(_j.dumps(
        {"parts": [{"n": н} for н in (1, 2, 3)], "total": 3, "budget_s": 35},
        ensure_ascii=False), encoding="utf-8")
    (арт / "часть1.json").write_text(_j.dumps(
        {"part": 1, "name": "1/3", "files": [], "sec": 10.0, "status": "ok",
         "tail": "1 passed", "failed": []}, ensure_ascii=False), encoding="utf-8")
    с = полигон.сводка_ci(арт)
    assert с["verdict"] == "RED" and any("неполный" in п for п in с["problems"]), с
    (арт / "часть2.json").write_text(_j.dumps(
        {"part": 2, "name": "2/3", "files": [], "sec": 9.0, "status": "ok",
         "tail": "1 passed", "failed": []}, ensure_ascii=False), encoding="utf-8")
    (арт / "часть3.json").write_text(_j.dumps(
        {"part": 3, "name": "3/3", "files": [], "sec": 8.0, "status": "ok",
         "tail": "1 passed", "failed": []}, ensure_ascii=False), encoding="utf-8")
    assert полигон.сводка_ci(арт)["verdict"] == "PROD-READY", полигон.сводка_ci(арт)


def test_клетка_ci_не_наследует_журнал_дома(tmp_path, monkeypatch):
    """История мер дома не есть мера клетки: в CI журнал прогонов чистится,
    иначе части «берутся из журнала» и ничего не мерят."""
    import json as _j
    import полигон
    дом = _клетка(tmp_path)
    журнал = дом / "00_START" / "полигон_журнал.json"
    журнал.write_text(_j.dumps({"части": [{"номер": 1, "имя": "фотон 1/1",
                                           "файлы": ["тесты_м.py"],
                                           "секунд": 20.0, "статус": "ок",
                                           "хвост": "1 passed",
                                           "время_с": 12.0}],
                                "бюджет_с": 45, "состояние": "готов"},
                               ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    отчёт = полигон.подготовить_клетку(дом)
    assert отчёт["журнал_чист"] is True, отчёт
    ж = полигон.загрузить(дом)
    ч1 = ж["части"][0]
    assert ч1.get("статус") == "ждёт" and not ч1.get("время_с"), ч1  # мера — заново
    assert ж["состояние"] == "идёт", ж["состояние"]
    # и часть снова МЕРИТСЯ, а не «берётся из журнала»
    ок, хвост, _ = полигон.часть(дом, 1, куда=tmp_path / "арт")
    assert ок and "из журнала" not in хвост, (хвост,)


def test_клетка_ci_строит_план_по_текущей_мере(tmp_path, monkeypatch):
    """Новый тест дома обязан попасть в прогон CI: клетка пересобирает план по
    мере, а не наследует замороженный (иначе тесты_сети.py молча не бежит)."""
    import json as _j
    import полигон
    дом = _клетка(tmp_path)
    # «вчерашний» замороженный план — без нового файла
    (дом / "00_START" / "полигон_журнал.json").write_text(_j.dumps(
        {"части": [{"номер": 1, "имя": "старый", "файлы": ["тесты_м.py"],
                    "секунд": 20.0, "статус": "ок"}],
         "бюджет_с": 45, "состояние": "готов"}, ensure_ascii=False),
        encoding="utf-8")
    (дом / "examples" / "тесты_новый.py").write_text(
        "def test_новое():\n    assert True\n", encoding="utf-8")
    (дом / "00_START" / "время_тестов.json").write_text(_j.dumps(
        {"файлы": {"тесты_м.py": 20.0, "тесты_н.py": 20.0, "тесты_новый.py": 0.1}},
        ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    полигон.подготовить_клетку(дом)
    ж = полигон.загрузить(дом)
    узлы = {str(ф) for ч in ж["части"] for ф in ч["файлы"]}
    assert any("тесты_новый.py" in у for у in узлы), узлы
    assert all(ч.get("статус") == "ждёт" for ч in ж["части"]), ж["части"]
    assert all(not ч.get("время_с") for ч in ж["части"]), ж["части"]


def test_workflows_контура_валидны_для_github():
    """Наказание протоколом (дважды грабли 30.09): job id кириллицей и двоеточие
    в имени шага делают ВЕСЬ workflow недействительным — GitHub падает за 0 с без
    job'ов. Проверка дешёвая: файлы контура разбираются строго, id — латиница,
    имена шагов — без двоеточий и табов. Ловим дома, а не в прогоне."""
    import re as _re
    контур = Path(__file__).resolve().parent.parent / ".github" / "workflows"
    файлы = sorted(контур.glob("*.yml"))
    assert файлы, "контур GitHub не найден"
    есть_yaml = True
    try:
        import yaml
    except Exception:                            # noqa: BLE001 — в клетке yaml может не быть
        есть_yaml = False
    for ф in файлы:
        текст = ф.read_text(encoding="utf-8")
        assert "\t" not in текст, f"{ф.name}: таб в YAML"
        for строка in текст.splitlines():
            м = _re.match(r"\s*(?:-\s*)?name:\s*(.+)$", строка)
            if м:
                имя = м.group(1).strip().strip("'\"")
                if "${{" in имя:                # выражения GitHub — не скаляр YAML
                    continue
                assert ": " not in имя and not имя.endswith(":"), \
                    f"{ф.name}: двоеточие в имени «{имя}» ломает YAML"
        if есть_yaml:
            д = yaml.safe_load(текст)            # строгий разбор: мусор — исключение
            for ид in (д.get("jobs") or {}):
                assert _re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", ид), \
                    f"{ф.name}: job id «{ид}» не ASCII — workflow станет недействительным"
            for ж in (д.get("jobs") or {}).values():
                for ш in ж.get("steps", []):
                    ид = ш.get("id")
                    if ид:
                        assert _re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", ид), \
                            f"{ф.name}: id шага «{ид}» не ASCII"

# ── сторож контура (грабли, повторённые дважды: 30.09) ─────────────────────
# Первый раз: кириллический job id → прогон падает без задач. Второй раз:
# двоеточие в имени шага («in one runner: one after another») → YAML не
# разбирается вовсе. Наказание — протоколом: файлы контура судятся строго.

def _воркфлоу() -> list:
    корень = Path(__file__).resolve().parent.parent
    return sorted((корень / ".github" / "workflows").glob("*.yml"))


def test_файлы_контура_разбираются_yaml_строго():
    import pytest as _пт
    yaml = _пт.importorskip("yaml")
    for ф in _воркфлоу():
        текст = ф.read_text(encoding="utf-8")
        try:
            yaml.load(текст, Loader=yaml.SafeLoader)
        except yaml.YAMLError as беда:
            raise AssertionError(f"{ф.name}: YAML не разбирается — {беда}") from беда


def test_имена_шагов_без_двоеточий_и_табов():
    """Плоский скаляр с «: » или табом — не YAML; сторож ловит ДО сервера."""
    for ф in _воркфлоу():
        for н, строка in enumerate(ф.read_text(encoding="utf-8").splitlines(), 1):
            голая = строка.strip()
            if голая.startswith("- name:"):
                значение = голая[len("- name:"):].strip().strip('"\'')
                assert ":" not in значение,                     f"{ф.name}:{н}: двоеточие в имени шага — {значение[:50]}"
            assert "\t" not in строка, f"{ф.name}:{н}: таб в YAML"


def test_идентификаторы_контура_латиницей():
    """job id и step id — только [A-Za-z0-9_-]: кириллица в ключе убивает прогон."""
    import re
    ок = re.compile(r"^[A-Za-z0-9_-]+$")
    for ф in _воркфлоу():
        for н, строка in enumerate(ф.read_text(encoding="utf-8").splitlines(), 1):
            голая = строка.strip()
            for метка in ("- id:", "id:"):
                if голая.startswith(метка):
                    значение = голая[len(метка):].strip().strip('"\'')
                    assert ок.match(значение),                         f"{ф.name}:{н}: id «{значение}» не латиница"

def test_действия_контура_закреплены_по_sha():
    """Х-20-5 (30.09): действие в воркфлоу — по ПОЛНОМУ SHA, не по ярлыку.

    Ярлык (`actions/checkout@v7`) — подвижная мишень: чужой репозиторий может
    переписать тег под нами (атака на цепочку поставок). SHA неподвижен; ярлык
    остаётся КОММЕНТАРИЕМ — по нему читают люди, обновляют осознанно.
    """
    import re
    отпечаток = re.compile(r"^uses:\s*([^\s#]+)\s*(#\s*(\S+))?\s*$")
    for ф in _воркфлоу():
        for н, строка in enumerate(ф.read_text(encoding="utf-8").splitlines(), 1):
            м = отпечаток.match(строка.strip())
            if not м:
                continue
            узел, _, ярлык = м.group(1), м.group(2), м.group(3)
            if узел.startswith("./"):
                continue                       # своё действие — чужого не тянуть
            имя, знак, версия = узел.partition("@")
            assert знак and re.fullmatch(r"[0-9a-f]{40}", версия), \
                f"{ф.name}:{н}: «{узел}» не закреплён по SHA"
            assert ярлык, f"{ф.name}:{н}: у закрепления нет ярлыка-комментария"

def test_владелец_жив_в_режиме_скрипта():
    """П-2, грабли CI (30.09): секции владельца стояли НИЖЕ стража runpy —
    при запуске файлом главное() звалось раньше, чем определялись константы
    («NameError: ПРЕДЕЛ_ВЫЗОВА_С»), и plan-джоба полигона падала на GitHub
    (прогон 36786757045: part-матрица пришла пустой). Клетка: скрипт обязан
    отдать план по измеренной мере — тем же расчётом, что дома.
    """
    import json
    import subprocess
    import sys
    корень = Path(__file__).resolve().parent.parent
    р = subprocess.run([sys.executable, "examples/полигон.py", "--plan-json"],
                       cwd=корень, capture_output=True, text=True, timeout=44)
    assert р.returncode == 0, (р.stdout[-300:], р.stderr[-300:])
    д = json.loads(р.stdout)
    assert д["parts"] and д["total"] == len(д["parts"]), д
    assert д["budget_s"] <= 45, д
    assert {"n", "name", "sec", "units", "files"} <= set(д["parts"][0]), д["parts"][0]

def test_сканеры_ворота_и_пины():
    """Х-20-5 (слой 5): свои сканеры вместо платных Code/Secret Protection.

    Клетка сторожа контура: в «воротах» есть задача сканеров, чужое действие
    секрет-сканера закреплено коммит-SHA с ярлыком, снасти запинены по версии,
    а предложения обновлений (dependabot) объявлены — пины не гниют молча.
    """
    import re
    корень = Path(__file__).resolve().parent.parent
    текст = (корень / ".github/workflows/tests.yml").read_text(encoding="utf-8")
    assert "skanery:" in текст, "нет задачи своих сканеров"
    найдено = re.findall(r"uses:\s+gitleaks/gitleaks-action@([0-9a-f]{40})\s+#\s*(\S+)", текст)
    assert найдено, "gitleaks не закреплён коммит-SHA с ярлыком"
    assert "ruff check" in текст and "--select" in текст, "нет сканера багов"
    assert "pip_audit" in текст or "pip-audit" in текст, "нет сканера уязвимостей"
    снасти = (корень / "requirements-skanery.txt").read_text(encoding="utf-8")
    строки = [с.strip() for с in снасти.splitlines()
              if с.strip() and not с.strip().startswith("#")]
    assert строки and all("==" in с for с in строки), f"снасти не запинены: {строки}"
    дов = (корень / ".github/dependabot.yml").read_text(encoding="utf-8")
    assert "package-ecosystem: \"pip\"" in дов and "github-actions" in дов, дов[:120]


def test_п6_части_становятся_местами_после_20_мин():
    """П-6: полный прогон >20 мин — раскладка «по местам», каждой части своё место."""
    import полигон
    долгий = {"части": [{"секунд": 300.0}, {"секунд": 300.0},
                        {"секунд": 300.0}, {"секунд": 400.0}]}
    р = полигон.раскладка(долгий)
    assert р["способ"] == "по местам" and р["мест"] == 4
    короткий = {"части": [{"секунд": 100.0}, {"секунд": 142.5}]}
    р2 = полигон.раскладка(короткий)
    assert р2["способ"] == "по времени" and р2["мест"] == 0


def test_сквозной_итог_через_cli(tmp_path):
    """Сквозной `--итог` (хвост 01.10): CLI-контур целиком — `--начать` →
    все части подряд → `--итог` обязан сказать «готов» и вернуть 0.

    Проверяем не функции, а путь, которым идёт дом и GitHub: одни и те же
    команды, коды возврата, строки итога (Статья 56: каждая часть ≤45 с)."""
    import os
    import subprocess
    import sys
    корень = Path(__file__).resolve().parent.parent
    дом = _клетка(tmp_path)
    скрипт = str(корень / "examples/полигон.py")
    # На раннере GitHub полигон «подготавливает клетку» при КАЖДОМ вызове
    # (матрица: каждый раннер свежий) — статусы частей обнулялись бы между
    # вызовами сквозного прогона. Сквозной контур идёт домашним путём:
    # CI-подготовка выключена явно (грабли 01.10, прогон 36846892934).
    среда = {к: v for к, v in os.environ.items() if к != "GITHUB_ACTIONS"}

    р = subprocess.run([sys.executable, скрипт, str(дом), "--начать"],
                       capture_output=True, text=True, timeout=44, env=среда)
    assert р.returncode == 0, (р.stdout[-300:], р.stderr[-300:])

    части = json.loads(subprocess.run(
        [sys.executable, скрипт, str(дом), "--план-json"],
        capture_output=True, text=True, timeout=44, env=среда).stdout)
    assert части["части"], части

    for ч in части["части"]:
        вызов = subprocess.run([sys.executable, скрипт, str(дом),
                                "--часть", str(ч["номер"])],
                               capture_output=True, text=True, timeout=44,
                               env=среда)
        assert вызов.returncode == 0, (ч["номер"], вызов.stdout[-300:])

    итог = subprocess.run([sys.executable, скрипт, str(дом), "--итог"],
                          capture_output=True, text=True, timeout=44,
                          env=среда)
    assert итог.returncode == 0, (итог.stdout[-300:], итог.stderr[-300:])
    assert "готов" in итог.stdout, итог.stdout
    assert f"ок {части['всего']}/{части['всего']}" in итог.stdout, итог.stdout



def test_ст_фотонности_сумма_попыток_части():
    """Закон Фотонности: сумма попыток части ≤ потолка вызова (было 45+30=75с)."""
    import полигон
    for предел in (15, 20, 30, 45, 60, 90):
        первая, вторая = полигон.попытки_части(предел)
        assert первая + вторая <= полигон.ПРЕДЕЛ_ВЫЗОВА_С, f"предел {предел}"
        assert вторая <= первая, "пересдача не может быть длиннее первой"
        assert первая >= 5 and вторая >= 5


def test_план_ci_держит_запас_раннера(tmp_path):
    """Раннер GitHub медленнее дома — план для матрицы режется ТЕСНЕЕ.

    Улика 01.10: CI-часть «сети+снасти+боя» вмерзла на 45 с (артефакт
    part-5, «ТАЙМАУТ >10с»), дома те же файлы — ~28 с. Значит, домашний
    замер нельзя нести в CI один в один: нужен запас ×1,5.
    """
    import полигон
    дом = _клетка(tmp_path)
    ж = полигон.план_ci(дом)
    assert ж["budget_s"] == полигон.БЮДЖЕТ_ЧАСТИ_С_CI < полигон.БЮДЖЕТ_ЧАСТИ_С, ж
    assert len(ж["parts"]) >= 2, ж            # запас реально дробит теснее
    assert all(ч["sec"] <= полигон.БЮДЖЕТ_ЧАСТИ_С_CI for ч in ж["parts"]), ж


def test_клетка_ci_не_ломает_план_матрицы(tmp_path, monkeypatch):
    """Подготовка клетки в CI обязана оставить ТОТ ЖЕ план, что у матрицы.

    Улика 01.10 (run 36865167429): клетка пересобирала журнал ДОМАШНИМ
    бюджетом (1 часть), матрица пришла на 2 — части за её краем падали
    «части N нет в плане». Первые семь зелёные, хвост красный — тихая
    гонка плана, а не дрожь раннера.
    """
    import полигон
    дом = _клетка(tmp_path)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    полигон.подготовить_клетку(дом)
    ж = полигон.загрузить(дом)
    м = полигон.план_ci(дом)
    assert ж["бюджет_с"] == полигон.БЮДЖЕТ_ЧАСТИ_С_CI, ж["бюджет_с"]
    assert len(ж["части"]) == len(м["parts"]), (len(ж["части"]), len(м["parts"]))


def test_предел_части_живёт_по_закону_фотонности(tmp_path):
    """Предел части — план+20, но не выше 45 (закон Фотонности).

    Улика 01.10: при CI-бюджете 20 часть с планом 29.1с дома бежала 57с на
    раннере и убивалась колпаком 50 — формула «бюджет+20» резала её до 40.
    """
    import полигон
    дом = _клетка(tmp_path)
    полигон.начать(дом, бюджет_с=полигон.БЮДЖЕТ_ЧАСТИ_С_CI)
    assert полигон.предел_части({"секунд": 30}, дом) == 45, \
        "план+20, но не выше закона"
    assert полигон.предел_части({"секунд": 20}, дом) == 40
    assert полигон.предел_части({"секунд": 5}, дом) == 25


def test_публичный_контур_без_приватного():
    """Х-20-8/ст.63: контур полигона для открытого репозитория собирается
    ЗАМЫКАНИЕМ импортов — журналы, уроки и ключевые места в снимок не
    попадают по построению, а сторож не пропускает ни секрета, ни метки
    закрытого дома.

    Живые уроки первого снимка (01.10): ворота дома (`tests.yml`) и
    `dependabot.yml` в открытом репозитории запускаются сами, падают без
    журналов и жгут минуты — потому файлов корня в контуре нет, а из клеток
    исключены те, что читают ворота (названы, не спрятаны). И кириллический
    ключ во входе workflow делает файл негодным: Actions молча зовёт контур
    путём, и все клетки падают на «Object» — сторож ключей это ловит.
    """
    import sys as _с
    from pathlib import Path as _П
    _с.path.insert(0, str(_П(__file__).resolve().parent))
    import публичный_полигон as пп

    снимок = пп.контур()
    # 1) контур — машинерия и клетки, а не копия каталога
    for нужный in ("examples/полигон.py", "examples/сеть.py", "README.md",
                   ".github/workflows/poligon.yml"):
        assert нужный in снимок, f"в контуре нет {нужный}"
    # 2) приватных корней нет — ни одного файла
    for путь in снимок:
        первый = путь.split("/", 1)[0]
        assert первый in ("examples", ".github", "README.md"), путь
    # 3) сторож: секрет, метка закрытого дома — находка; чистый снимок — пусто
    плохо = dict(снимок)
    плохо["examples/дыра.py"] = "т = 'ghp_" + "A" * 30 + "'"
    assert any("секрет" in н for н in пп.сторож(плохо)), "секрет не пойман"
    плохо2 = dict(снимок)
    плохо2["examples/вердикт.py"] = 'РЕПО = "sergey1772/poligon"'
    assert any("метка" in н for н in пп.сторож(плохо2)), "метка дома не поймана"
    assert пп.сторож(снимок) == []
    # 4) ключи workflow — ASCII (иначе Actions зовёт контур путём)
    свой = снимок[".github/workflows/poligon.yml"]
    assert not пп._годен_workflow(свой), "workflow контура негоден"
    assert пп._годен_workflow(свой.replace("  push:", "  пуш:")), \
        "кириллический ключ не пойман"
    # 5) клетки и отборы — из одного источника; исключённое НАЗВАНО
    assert "examples/тесты_полигона.py" in пп.ВХОДЫ
    assert "examples/тесты_сети.py" not in пп.ВХОДЫ, \
        "живая клетка сети меряет hit@1 по полному дому — в контуре красна"
    for цель, отбор in пп.КРОМЕ.items():
        assert цель in пп.ВХОДЫ and отбор.startswith("not "), (цель, отбор)
        assert цель in снимок
    # 6) расхождение контура ловит РИТМ, а не память: шаг есть в единственном
    #    списке (строчный сторож — импорт ритма утащил бы в снимок пол-дома)
    ритм = (_П(__file__).resolve().parent / "боевой_ритм.py").read_text(
        encoding="utf-8")
    assert '"публичный контур"' in ритм and "_публичный_контур" in ритм, \
        "шага сверки публичного контура нет в ритме"
