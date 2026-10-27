# Архитектурная спецификация: Модульный C++/ObjC++ плагин `FLM_CustomDSP.dylib`

## 0. ПРАВИЛА ЭКОНОМИИ ТОКЕНОВ И МОДУЛЬНОЙ РАЗРАБОТКИ (СТРОГО)
1. **ИЗОЛЯЦИЯ ЭТАПОВ:** Мы разрабатываем плагин строго по одному этапу (Stage) за раз. Никогда не пиши код будущих этапов заранее — оставляй для них только легкие пустые заглушки (`Pass-through`).
2. **НЕ ЧИТАТЬ БИНАРНИКИ:** Не читай `target.ipa` или `dist/FLM_Custom*.ipa` целиком. Инъекция `.dylib` в Mach-O бинарник `FL Studio Mobile` выполняется чистым Python-скриптом через модификацию заголовка (`LC_LOAD_DYLIB`).
3. **ТЕКУЩИЕ ЗАГЛУШКИ (НЕ РЕАЛИЗОВАНЫ / НЕ СКОМПИЛИРОВАНЫ ЛОКАЛЬНО):** `Mod2_VocalTune`, `Mod3_TimeGlitch`, `Mod4_LoFiSpace`, `Mod5_AUv3Rec` работают только как `Pass-through` заглушки; локальный файл `build/FLM_CustomDSP.dylib` на Windows без прогона macOS CI является Mach-O заглушкой (требуется сборка в CI — уровень B, и проверка на устройстве — уровень C).
4. **ЧИСТАЯ СТРУКТУРА ФАЙЛОВ (`plugin_src/`):**
   ```text
   plugin_src/
   ├── core/
   │   ├── DylibEntry.mm        # Точка входа __attribute__((constructor)), Crash-Guard, 1 Гц os_log таймер, UI
   │   ├── AudioHook.h/.mm      # Перехват RemoteIO AudioUnit (Input Mic & Output Master) + fishhook + атомарные счетчики
   │   ├── DSPModule.h          # Базовый C++ интерфейс для всех эффектов: process(float* L, float* R, int frames, float sr)
   │   └── RackChain.h/.cpp     # Последовательная цепочка из 5 модулей с атомарным Bypass и кольцевым буфером
   ├── ui/
   │   ├── FloatingOverlay.h/.mm # Плавающая кнопка и главное окно 520x336 pt (Pure Black #080808, Oxblood #6B0F1A/#8A1222, Chrome #D4D4D8)
   │   └── WaveformView.h/.mm    # Отрисовка осциллографа 60 FPS в реальном времени
   ├── sim_host/
   │   └── SimHostApp.mm        # Минимальный хост под iphonesimulator для съема нативных скриншотов в CI
   ├── modules/
   │   ├── Mod1_Brutalizer.h/.cpp # Stage 1: 808 Sub-Octave, Diode Saturator, Hard Clipper + Mid/Side Mono (<120Hz)
   │   ├── Mod2_VocalTune.h       # Заглушка Stage 2 (Pass-through)
   │   ├── Mod3_TimeGlitch.h      # Заглушка Stage 3 (Pass-through)
   │   ├── Mod4_LoFiSpace.h       # Заглушка Stage 4 (Pass-through)
   │   └── Mod5_AUv3Rec.h         # Заглушка Stage 5 (Pass-through)
   └── vendor/
       └── fishhook.h/.c        # Перехват таблиц символов Mach-O (__DATA / __DATA_CONST)
   ```

## 1. АРХИТЕКТУРА ПЕРЕХВАТА АУДИО (CORE AUDIO HOOK)
- Перехватываются функции `AudioUnitSetProperty`, `AudioUnitRender` и `AudioOutputUnitStart` системного `AudioToolbox` через `fishhook`.
- Когда FL Studio Mobile регистрирует `kAudioUnitProperty_SetRenderCallback` на `RemoteIO` юните, хук сохраняет оригинальный коллбэк DAW и подставляет `CustomMasterRenderCallback`.
- В режиме **OUTPUT (Master)** вызывается оригинальный рендер DAW, затем буфер проходит через `RackChain::process()`. В режиме **INPUT (Mic)** перехватывается `AudioUnitRender` на входной шине (bus 1).
- Все параметры и диагностические счетчики (`cb`, `frames`, `SR`, `mode`) передаются между UI и аудио-потоком строго через `std::atomic` (Lock-Free; никаких `os_log`, ObjC-вызовов или аллокаций памяти в аудио-потоке).

## 2. ДИЗАЙН ИНТЕРФЕЙСА (UI OVERLAY)
- **Плавающая кнопка:** Круг `44x44 pt`, перетаскиваемый по экрану с учетом динамических `safeAreaInsets` активного `UIWindow`, фон `#080808` (альфа 0.9), хромированная обводка `#D4D4D8` и бордовый индикатор активности.
- **Главное окно плагина:** Панель по центру экрана **`520x336 pt`** в Landscape (клампится по `safeAreaInsets`), скругление `14 pt`, цвет фона `#080808`, панели `#121214`, акценты — `#6B0F1A` / `#8A1222`, текст — `#E4E4E7`.
- **Шапка окна (высота `60 pt`):** Заголовок, строка живой диагностики (`HOOK: OFF/OK | cb=N | frames=N | SR=... | mode`), живой осциллограф волны и кнопки управления **`MODE`**, **`SNAP`**, **`ACTIVE`**, **`HIDE`** (визуальная высота `32 pt`, расширенная `hit-area 44 pt` через `pointInside:withEvent:` без пересечения соседей).
- **Вкладки и контролы:** Переключатель 5 вкладок (`1. 808/CLIP` .. `5. AUv3/REC`) и 4 слайдера Модуля 1 (`hit-area 44 pt`).

## 3. ДОРОЖНАЯ КАРТА ЭТАПОВ (STAGES)
- **STAGE 1 (Выполнен локально — Уровень A):** Каркас `plugin_src/`, CoreAudio Hook, UI Overlay с осциллографом, **Модуль 1 (808 Brutalizer & Hard Clipper)**, скрипты патчинга Mach-O и workflow `.github/workflows/build_ios_dylib.yml`.
- **STAGE 1.5 (Выполнен локально — Уровень A):** Авто-аудит геометрии `scripts/ui_vision_audit.py`, Wi-Fi телеметрия `SNAP` + `scripts/ui_receiver.py`, хост симулятора `SimHostApp.mm` для CI.
- **STAGE 1.6 (Текущий — Фундамент и смоук-тест):** Проверка импортов Mach-O (`scripts/check_audio_imports.py`), размещение в `Frameworks/FLM_CustomDSP.dylib` (`@rpath`), двойная сборка `FLM_Custom_NoDylib.ipa` и `FLM_Custom_Hook.ipa`, Crash-Guard (`boot_count` / ` SAFE MODE`), живая строка диагностики + `os_log` 1 Гц, динамические `safeAreaInsets` + `pointInside:withEvent:` (`44 pt` hit-area), патч `Info.plist` для локальной сети.
- **STAGE 2..5 (Ожидают завершения смоук-теста Stage 1.6 на устройстве):** `Mod2_VocalTune`, `Mod3_TimeGlitch`, `Mod4_LoFiSpace`, `Mod5_AUv3Rec`.
