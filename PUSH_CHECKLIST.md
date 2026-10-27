# Чек-лист перед отправкой в GitHub (`PUSH_CHECKLIST.md`)

## 1. Что РАЗРЕШЕНО добавлять в Git (только чистый код и конфиги)
- `plugin_src/` — исходники плагина C++/ObjC++ (`core/`, `modules/`, `ui/`, `sim_host/`, `vendor/`)
- `.github/workflows/build_ios_dylib.yml` — пайплайн сборки `FLM_CustomDSP.dylib` (Job 1) и скриншотов симулятора (Job 2)
- `scripts/` — только Python-скрипты (`ui_vision_audit.py`, `ui_receiver.py`, `patch_macho_dylib.py`, `inject_dylib_to_ipa.py`, `inject_ipa.py`, `check_audio_imports.py`, `dwp_lib.py`, `build_instruments.py`)
- `.gitignore`, `AGENT_SPEC.md`, `PLUGIN_SPEC.md`, `PUSH_CHECKLIST.md`

## 2. Что КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО пушить
- `target.ipa` и любые файлы `*.ipa`
- `dist/` (собранные `.ipa`, `.dwp` и `.wav`/FLAC-сэмплы)
- `workspace/` (`samples_ref/`, донорские `.dwp`/`.wav` извлечённые из `.ipa`, `recon_state.json`, `ui_snapshots/`)
- `build/` и любые `*.dylib`, `*.o`
- `input_samples/`

## 3. Команды проверки перед `git commit` и `git push`
```powershell
git init
git add .gitignore plugin_src .github scripts AGENT_SPEC.md PLUGIN_SPEC.md PUSH_CHECKLIST.md
git status
```
**Контроль `git status`:**
1. В списке `Changes to be committed` **не должно быть** ни одного файла из `workspace/`, `dist/`, `build/` или `*.ipa` / `*.dwp` / `*.wav`.
2. Проверить, что ни один бинарный/аудио файл не попал в индекс (`результат должен быть пустым`):
   ```powershell
   git ls-files | Select-String -Pattern '\.(ipa|dwp|flac|wav|dylib)$'
   ```
3. Проверить, что запрещённые папки игнорируются:
   ```powershell
   git status --ignored
   ```
   (`target.ipa`, `dist/`, `workspace/`, `build/` должны отображаться только в секции `Ignored files`).
