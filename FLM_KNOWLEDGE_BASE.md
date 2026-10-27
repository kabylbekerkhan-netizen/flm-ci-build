# FL Studio Mobile (iOS) — Инженерная база знаний и архитектурные инсайты

Документ фиксирует проверенные на практике (локально `[A]`, в облачном macOS CI `[B]` и на реальном iPhone с iOS 26.6.2 `arm64e` `[C]`) технические решения, структуры бинарных форматов и рабочие процессы для разработки плагинов, инструментов и модификаций под **FL Studio Mobile v4.10.1 (`com.imageline.FLStudioMobileHD`)**.

---

## 1. Формат инструментов DirectWave (`.dwp` / `DwPr`) и `samplesList.data`

1. **Заголовок и глобальная секция `.dwp`:**
   - Магическая сигнатура: `DwPr` (первые 4 байта), общий размер заголовка — `36 B`.
   - Глобальный блок параметров программы: байты `[36..484)` (`448 B`).
   - Количество сэмпл-зон (`zone_count`): `int32` little-endian в байтах `[484..488)`.
2. **Структура одной зоны (`176 B` + UTF-16LE путь + `72 B` суффикс):**
   - Заголовок зоны (`176 B`):
     - `z[22]` (`uint8`): опорная нота (`pitch_root`, например `60` = C4).
     - `z[24]`, `z[25]` (`uint8`): диапазон клавиш (`key_min` .. `key_max`).
     - `z[26]`, `z[27]` (`uint8`): диапазон велосити (`vel_min` .. `vel_max`, обычно `1..127`).
     - `z[120:124]` (`int32`): усиление зоны (`gain_db_int`).
   - Путь к сэмплу: `uint8` длина строки в байтах + `UTF-16LE` строка вида `InstrumentName/InstrumentName_01.wav\x00`.
   - Пост-блок зоны (`72 B`): последние `32 B` являются инвариантным трейлером (идентичны во всех заводских `.dwp`).
3. **Формат аудио-сэмплов:**
   - Несмотря на расширение файла `.wav`, внутри контейнера лежит чистый поток **FLAC (`fLaC`, 44 100 Гц, 16-bit, mono)**. Обычный несжатый RIFF PCM WAV в заводских мульти-инструментах не используется для экономии места, но декодер FLM читает FLAC напрямую из файлов с расширением `.wav`.
4. **Индекс заводского браузера (`samplesList.data`):**
   - Первые 4 байта: `uint32` число записей (`383` в оригинале → `386` после добавления 3 кастомных инструментов).
   - Далее идут фиксированные структуры по `132 B`: `128 B` нуль-терминированная ASCII/UTF-8 строка имени + `uint32` код категории (`1` = Keyboard, `8` = Guitar, `10` = Synth Bass).
   - Чтобы инструмент появился в заводских вкладках без ручного импорта, код категории и формат блока в `.dwp` клонируются от донора той же категории (`Purity Guitar`, `Ogun Clockwork`, `Morphine Clavinet`).

---

## 2. Mach-O архитектура `FL Studio Mobile` и инъекция `.dylib`

1. **Таблицы символов и импорты:**
   - Главный бинарник `Payload/FL Studio Mobile.app/FL Studio Mobile` — 64-битный `MH_EXECUTE` (`CPU_TYPE_ARM64 = 0x0100000C`), использующий классические таблицы `LC_SYMTAB` + `LC_DYLD_INFO_ONLY` (без `LC_DYLD_CHAINED_FIXUPS`).
   - Запас пустого места (`header padding`) между концом существующих команд загрузки (`ncmds = 51`, `sizeofcmds = 6160`) и первой секцией кода `__TEXT,__text` (`offset 16384`) составляет **`10 168 B`**, что позволяет дописывать команду `LC_LOAD_DYLIB` (`56 B`) без пересборки сегментов.
2. **Пути `@rpath` и подпись:**
   - В бинарнике уже прописаны `LC_RPATH = ['@executable_path/Frameworks', '@loader_path/Frameworks']`.
   - Поэтому кастомная библиотека должна компилироваться с `-install_name "@rpath/FLM_CustomDSP.dylib"`, подписываться `codesign -f -s -` и укладываться в `Payload/FL Studio Mobile.app/Frameworks/FLM_CustomDSP.dylib` с правами `0755` (`external_attr = 0o100755 << 16` в ZIP).
3. **Особенность `fishhook` на современном iOS (`__DATA_CONST`):**
   - Таблицы указателей `__la_symbol_ptr` и `__got` в сегменте `__DATA_CONST` после связывания `dyld` переводятся в `read-only`. Перед перезаписью указателя в `fishhook.c` обязателен вызов `vm_protect(mach_task_self(), page, PAGE_SIZE, false, VM_PROT_READ | VM_PROT_WRITE | VM_PROT_COPY)`.

---

## 3. CoreAudio конвейер FL Studio Mobile на реальном iPhone

1. **Подтверждённая точка перехвата (`RemoteIO`):**
   - `FL Studio Mobile` не использует `AUGraph`, `AudioQueue` или `AVAudioEngine` — весь вывод идёт напрямую через C API `AudioToolbox`: `AudioComponentInstanceNew` → `AudioUnitSetProperty` (`kAudioUnitProperty_SetRenderCallback`, `inScope = kAudioUnitScope_Input` или `Global`, `inElement = 0`) → `AudioUnitInitialize` → `AudioOutputUnitStart`.
2. **Реальные параметры аудио-потока на устройстве (iPhone, iOS 26.6.2):**
   - Частота дискретизации: **`SR = 48 000 Гц`** (важно: все DSP-фильтры, питч-трекеры и буферы задержки должны опираться на динамический `sampleRate` из `ASBD`, а не на хардкод `44100`).
   - Размер буфера колбэка: **`frames = 256`** (~5.33 мс).
   - Формат данных: **`Float32 Planar` (`F32P`)** — неинтерливированный стерео-поток (`ioData->mNumberBuffers == 2`, `mBuffers[0]` = Left `float*`, `mBuffers[1]` = Right `float*`). При этом в `AudioHook.mm` сохранена поддержка и `Float32 Interleaved` (`F32I`), и безопасный `passthrough` для любых иных форматов.
3. **Жесткие правила Real-Time потока:**
   - Никогда не вызывать `AudioUnitGetProperty`, `os_log`, `malloc`/`new`, `std::vector::resize` или Objective-C сообщения внутри `CustomMasterRenderCallback`.
   - Чтение `AudioStreamBasicDescription` выполняется только при инициализации/старте юнита (`Hooked_AudioUnitSetProperty`, `Hooked_AudioUnitInitialize`, `Hooked_AudioOutputUnitStart`).
   - На выходе цепочки обязательна санитизация `std::isfinite(x)` (`NaN`/`Inf` → `0.0f`) и жёсткий лимитер `std::clamp(x, -1.0f, 1.0f)`.
4. **Нюанс компиляции под Xcode 16 / iOS 18+ SDK (`macos-15`):**
   - В новых заголовках `AudioUnit` тип `AURenderCallback` имеет атрибут Clang Realtime Sanitizer `__attribute__((nonblocking))`. Прямое сравнение или присваивание обычной C-функции вызывает ошибку компиляции `comparison of distinct pointer types`; необходимо приведение `reinterpret_cast<AURenderCallback>(&CustomMasterRenderCallback)`.

---

## 4. UIKit Overlay, геометрия экрана и телеметрия

1. **Реальная геометрия на устройстве (`956 × 440 pt`, Landscape):**
   - Отступы безопасной зоны: `safeAreaInsets = [top=0, left=62, bottom=20, right=62]` (зона Dynamic Island занимает `62 pt` сбоку).
   - Главное окно `520 × 336 pt` и плавающая кнопка `44 × 44 pt` центрируются и клампятся по динамическим `window.safeAreaInsets`.
   - Подклассы `FLMHitButton` и `FLMHitSlider` с переопределённым `pointInside:withEvent:` расширяют физическую зону нажатия до `44 × 44 pt` при компактной визуальной высоте `32 pt` (подтверждено `0 issues` по `67` живым `UIView` на iPhone).
2. **Встроенный Crash-Guard:**
   - В `Documents/PluginHotReload/boot_count` при старте записывается счётчик запусков. Сброс в `0` происходит только когда одновременно `cb > 0` и прошло `>= 60 с` без падений. Если приложение упадёт 3 раза подряд (или создан `safe_mode.flag`), аудио-хук автоматически отключается (`SAFE MODE`).
3. **Снятие скриншотов и телеметрии (`SNAP`):**
   - Кнопка `SNAP` в шапке плагина сохраняет `Documents/ui_snap_latest.png` и `Documents/ui_snap_latest.json` локально в песочницу и параллельно отправляет их по HTTP POST на `ui_receiver.py`.

---

## 5. Деплой и отладка по USB Type-C без джейлбрейка (`scripts/ios_usb_tool.py`)

1. **Экономия лимитов бесплатного Apple Developer аккаунта (3 приложения / 10 App ID в неделю):**
   - Сохранение оригинального `CFBundleIdentifier` (`com.imageline.FLStudioMobileHD`) в `FLM_Custom_Hook.ipa` позволяет SideStore обновлять приложение (`com.imageline.FLStudioMobileHD.3Y9M8NLG82`) поверх существующего, не тратя новый App ID и не занимая дополнительный слот из 3 активных приложений.
2. **Прямой доступ к файловой системе через `usbmuxd` (`127.0.0.1:27015`) + `HouseArrest` + `AFC` (`CFA6LPAA`):**
   - Так как у `FL Studio Mobile` и `SideStore` в `Info.plist` включён `UIFileSharingEnabled = true`, скрипт `scripts/ios_usb_tool.py` (на чистом стандартном Python) напрямую по кабелю:
     - заливает новые `.ipa` в `SideStore/Documents` со скоростью `~19 МБ/с`;
     - заливает и обновляет инструменты `.dwp` и папки сэмплов в `FL Studio Mobile/Documents/My Instruments/` без переустановки приложения;
     - скачивает `ui_snap_latest.png`, `ui_snap_latest.json` и `PluginHotReload/boot_count` с устройства за 1 секунду.
