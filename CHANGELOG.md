# CHANGELOG

<!-- version list -->

## v0.26.2 (2026-07-30)

### Bug Fixes

- Keep file progress table rows stable by name
  ([`c755aae`](https://github.com/guozhijian611/hf-model-downloader/commit/c755aaec4bbd7c70ea9a65a77df236a603735235))


## v0.26.1 (2026-07-30)

### Bug Fixes

- Show real per-file progress from disk incomplete sizes
  ([`4a81387`](https://github.com/guozhijian611/hf-model-downloader/commit/4a8138750864bfa5d0864e556b0e0731a3d66ac1))


## v0.26.0 (2026-07-30)

### Chores

- Log when repo type validation is skipped
  ([`0bb7ebd`](https://github.com/guozhijian611/hf-model-downloader/commit/0bb7ebda4430bde3cd3c19dd8a142f5f3d2bb347))

### Features

- Add switch to skip Hugging Face repo type validation
  ([`ec23aa6`](https://github.com/guozhijian611/hf-model-downloader/commit/ec23aa6f71be36820fd156425a56ab8adac78c21))


## v0.25.0 (2026-07-30)

### Features

- Install jq for hfd and fix listing stall false positives
  ([`ae4a862`](https://github.com/guozhijian611/hf-model-downloader/commit/ae4a8622e78c218a18fa0dde8886685d8d0152ff))


## v0.24.0 (2026-07-29)

### Features

- Feed hfd/aria2 progress into the monitor panel
  ([`e7f47cf`](https://github.com/guozhijian611/hf-model-downloader/commit/e7f47cf8418875ce0c039117953ed6ae85409c44))


## v0.23.0 (2026-07-29)

### Features

- Per-file progress for huggingface-hub concurrent downloads
  ([`03c5dd9`](https://github.com/guozhijian611/hf-model-downloader/commit/03c5dd9b74d70a0c3bcd360b7aaaa27aeaa0f944))


## v0.22.0 (2026-07-29)

### Features

- Portable aria2 install on Windows without winget
  ([`47a28e9`](https://github.com/guozhijian611/hf-model-downloader/commit/47a28e901aa72fe656c0d9325db31eab9629dab1))


## v0.21.0 (2026-07-29)

### Features

- One-click install for missing hfd/aria2 dependencies
  ([`6ca80e6`](https://github.com/guozhijian611/hf-model-downloader/commit/6ca80e6697c3e2874a5deba0cb535fb23a9f4f76))


## v0.20.0 (2026-07-29)

### Features

- Add hour/day windows for traffic monitor history
  ([`1b1c783`](https://github.com/guozhijian611/hf-model-downloader/commit/1b1c7837f7b6a6733c23ad2a88139070cbd8fcb5))


## v0.19.2 (2026-07-29)

### Bug Fixes

- Wire HF hub proxy via httpx client factory
  ([`f62610f`](https://github.com/guozhijian611/hf-model-downloader/commit/f62610f948d44b7c1c7e6cc6be93e7767db4e92d))


## v0.19.1 (2026-07-29)

### Bug Fixes

- Speed up download start and clean up monitor UI
  ([`73a5f15`](https://github.com/guozhijian611/hf-model-downloader/commit/73a5f15587532b21b4c48a29134e2812cefda557))


## v0.19.0 (2026-07-29)

### Features

- Floating monitor window and fix file progress recognition
  ([`9058858`](https://github.com/guozhijian611/hf-model-downloader/commit/9058858cc732e88399ac9f9b66471cf7392b5edb))


## v0.18.1 (2026-07-29)

### Bug Fixes

- Restore check-update UI feedback after requests trust_env crash
  ([`49b45aa`](https://github.com/guozhijian611/hf-model-downloader/commit/49b45aabc2ef5f007174a4ab076e7477bb9f1612))


## v0.18.0 (2026-07-29)

### Features

- File progress panel and disk write speed monitoring
  ([`a3033f9`](https://github.com/guozhijian611/hf-model-downloader/commit/a3033f9ebcb9111d30f53b82b9362c798c23dda3))


## v0.17.0 (2026-07-29)

### Features

- Add network traffic monitor panel with speed history chart
  ([`a435c9b`](https://github.com/guozhijian611/hf-model-downloader/commit/a435c9b0fe6ec7fb527a557d1d4726e6ce095ea0))


## v0.16.0 (2026-07-29)

### Features

- Make auto-retry wait seconds user-configurable
  ([`d0c7b22`](https://github.com/guozhijian611/hf-model-downloader/commit/d0c7b224fec8141347be62e306be7ae170334304))


## v0.15.0 (2026-07-29)

### Features

- Run optional shell command when download stall restarts
  ([`0e6ebfa`](https://github.com/guozhijian611/hf-model-downloader/commit/0e6ebfa0f28f2fb1c3aee0046b9fac8a8fe5633d))


## v0.14.0 (2026-07-29)

### Features

- Expose hub and hfd concurrency settings in the UI
  ([`51c7d7f`](https://github.com/guozhijian611/hf-model-downloader/commit/51c7d7f729da57e758776f222d92a1d52d69d339))


## v0.13.1 (2026-07-29)

### Chores

- Sync embedded version metadata to v0.13.0
  ([`b0b29a2`](https://github.com/guozhijian611/hf-model-downloader/commit/b0b29a22c6a5d9073e71ac97211aa1aca21f40c8))


## v0.13.0 (2026-07-29)

### Features

- Auto-restart download when stalled with no progress
  ([`d3438d6`](https://github.com/guozhijian611/hf-model-downloader/commit/d3438d6debf75449ac2eeef6b8335cbdec2fa10b))


## v0.12.1 (2026-07-29)

### Bug Fixes

- **deps**: Add PySocks for socks5 proxy support
  ([`72d1394`](https://github.com/guozhijian611/hf-model-downloader/commit/72d1394e70dfbd65ff5d86cb569cda8bcb53dd4c))


## v0.12.0 (2026-07-29)

### Features

- Optional built-in hfd/aria2 download backend
  ([`795f1fb`](https://github.com/guozhijian611/hf-model-downloader/commit/795f1fb4291879894795282ba7ea8343b44cb997))


## v0.11.0 (2026-07-29)

### Features

- Multi endpoint presets with automatic failover
  ([`370dafe`](https://github.com/guozhijian611/hf-model-downloader/commit/370dafe7c45a78458696c1a0e05b7672eca0bd0e))


## v0.10.3 (2026-07-29)

### Bug Fixes

- **download**: Show real HF errors and harden mirror downloads
  ([`795b2e1`](https://github.com/guozhijian611/hf-model-downloader/commit/795b2e12fcce87f9b02cd05f2fc30cb8ebbcbe92))


## v0.10.2 (2026-07-29)

### Bug Fixes

- **update**: Make Windows in-place auto-update actually apply
  ([`a8cbbca`](https://github.com/guozhijian611/hf-model-downloader/commit/a8cbbca265d8f6fec77e3d48f74ad81aa2e1a8bc))


## v0.10.1 (2026-07-29)

### Bug Fixes

- **download**: Use Formatter.formatTime in UI log handler
  ([`d2eef6c`](https://github.com/guozhijian611/hf-model-downloader/commit/d2eef6c6518f8f095727cbbad2449aec8c5554e5))


## v0.10.0 (2026-07-29)

### Features

- Write runtime and crash logs to a local log directory
  ([`3dc3af5`](https://github.com/guozhijian611/hf-model-downloader/commit/3dc3af5f9f5e150f565ee1c228cd4fe705cdfac1))


## v0.9.1 (2026-07-29)

### Bug Fixes

- **download**: Prevent crash when starting downloads under Qt
  ([`d01d88a`](https://github.com/guozhijian611/hf-model-downloader/commit/d01d88ad4b077cd8f4fa6f0d723f57cce7004649))


## v0.9.0 (2026-07-29)

### Bug Fixes

- **ci**: Stop release pipeline from hanging on Intel mac runners
  ([`8976ed8`](https://github.com/guozhijian611/hf-model-downloader/commit/8976ed8c7667d83fa56611c2456b861b81389daa))

### Features

- Embed release version and auto-download in-place updates
  ([`8f58142`](https://github.com/guozhijian611/hf-model-downloader/commit/8f581427ce962d57186e5651fb700c65e4e1319d))


## v0.8.2 (2026-07-29)

### Continuous Integration

- Call multi-platform build from release workflow
  ([`b208877`](https://github.com/guozhijian611/hf-model-downloader/commit/b208877a3ae04e773d18f7d2da90941a192695b7))


## v0.8.1 (2026-07-29)

### Chores

- Sync app version metadata to 0.8.0
  ([`f885af2`](https://github.com/guozhijian611/hf-model-downloader/commit/f885af2e6dfea18ac73440cc9cab2d09bc240bca))


## v0.8.0 (2026-07-29)

### Features

- Add online update check against GitHub Releases
  ([`3c1e161`](https://github.com/guozhijian611/hf-model-downloader/commit/3c1e16100b30b78aaad51565c51a605b306ea65c))


## v0.7.0 (2026-07-29)

### Features

- Rebrand repo, persist settings, proxy, and auto-retry downloads
  ([`69de1c6`](https://github.com/guozhijian611/hf-model-downloader/commit/69de1c66054f551c803a5b05db01ae284d13b3fa))


## v0.6.2 (2026-07-07)

### Bug Fixes

- **download**: Bundle hf_xet, validate repo type, and migrate to uv
  ([`dea7183`](https://github.com/samzong/hf-model-downloader/commit/dea7183de126c7a4591299c982e373b824eec5eb))


## v0.6.1 (2025-08-22)

### Bug Fixes

- **website**: Add platform-specific download button for latest release
  ([`807ee49`](https://github.com/samzong/hf-model-downloader/commit/807ee49e0b2d7f3300962499327026be7bc96c1e))


## v0.6.0 (2025-08-22)

### Features

- **readme**: Add smart download button with OS detection and links
  ([`475e894`](https://github.com/samzong/hf-model-downloader/commit/475e894f973474a8ff246807af6bb5a848c2cc54))


## v0.5.5 (2025-08-22)

### Bug Fixes

- **dependencies**: Remove cli extra from huggingface-hub in config and requirements
  ([`7790e1c`](https://github.com/samzong/hf-model-downloader/commit/7790e1ca594d4e9da6d3d6d77a69572ab1e3623a))

### Documentation

- **build**: Update README with detailed make commands and cleanup release-guide.md removal
  ([`a46417d`](https://github.com/samzong/hf-model-downloader/commit/a46417d3dbe1cc296b5362fdf432c7f32082f795))


## v0.5.4 (2025-08-22)

### Chores

- **downloader**: Update deprecation warnings and messages for unified downloader
  ([`d0aeb67`](https://github.com/samzong/hf-model-downloader/commit/d0aeb676d3ce7bdbde8aafc0d9909aa8bbea8209))

- **makefile**: Improve python command detection and clean release echoes
  ([`f6704b4`](https://github.com/samzong/hf-model-downloader/commit/f6704b44739dbe3db4fd5748842b33952566e459))

### Refactoring

- **build**: Clean up build script and improve icon handling comments
  ([`428aa4e`](https://github.com/samzong/hf-model-downloader/commit/428aa4e3edfb6b74b1f9dd110d8903b9f5d73f95))

- **ci**: Streamline dependency installation and update python version to 3.13 in workflows
  ([`b2d693b`](https://github.com/samzong/hf-model-downloader/commit/b2d693b437d6f72b8b892610c2427e85101f4ab2))

- **icon-generator**: Remove deprecated icon_generator.py script and all related code
  ([`d57bfa1`](https://github.com/samzong/hf-model-downloader/commit/d57bfa1d3c94b4816b482a3b81d19a1f8bbfdcac))

- **makefile**: Simplify version detection and improve logging in build tasks
  ([`9d2b76a`](https://github.com/samzong/hf-model-downloader/commit/9d2b76a4f572ae426e5b68e0dbde482e93f9f3f0))

- **makefile**: Streamline dependency management and add linting targets
  ([`d7f1237`](https://github.com/samzong/hf-model-downloader/commit/d7f1237933c88f3747f6327dc995d2a25de66e37))

### Testing

- **tests/test_e2e_basic**: Remove trailing comments from model_id arguments
  ([`3eac90c`](https://github.com/samzong/hf-model-downloader/commit/3eac90c84e0e8b4a54c9d99c05c74bfb7ac9e008))


## v0.5.3 (2025-08-21)

### Chores

- Remove uv.lock from version control
  ([`4d54078`](https://github.com/samzong/hf-model-downloader/commit/4d540786f173d79e7797e77a45a9bb5a1ce12dc0))

- **dependencies**: Bump hf-model-downloader version to 0.5.2
  ([`a0a0245`](https://github.com/samzong/hf-model-downloader/commit/a0a0245dc704802f3ec820d7e174c9b717ad9136))

### Documentation

- **readme**: Update description and usage instructions for clarity and accuracy
  ([`4962c25`](https://github.com/samzong/hf-model-downloader/commit/4962c25422d4c44f91b40dfbb04d470ec77367d4))

- **readme**: Update screenshot image to reflect UI changes
  ([`dfdc440`](https://github.com/samzong/hf-model-downloader/commit/dfdc440f99860e5dd4a58c20641e71465ec0a005))

### Refactoring

- Clean up code and improve comments across multiple files
  ([`0c8540a`](https://github.com/samzong/hf-model-downloader/commit/0c8540a1e42ea288c54fd621020a60e10dac4553))


## v0.5.2 (2025-08-20)

### Bug Fixes

- **resource**: Add utility to load asset paths in development and packaged app
  ([`c5d7b26`](https://github.com/samzong/hf-model-downloader/commit/c5d7b2644d491340cf7bc9bc24b7e095d3a81a50))


## v0.5.1 (2025-08-20)

### Chores

- **dependencies**: Update hf-model-downloader version to 0.5.0 in uv.lock
  ([`2228db0`](https://github.com/samzong/hf-model-downloader/commit/2228db04e622f398895d4738cfa1f03ec8a1471a))

- **lint**: Add initial Ruff configuration file with selected rules and formatting
  ([`bff47ad`](https://github.com/samzong/hf-model-downloader/commit/bff47aded0fc4d8139eb24b90a5414ceb28fc205))

### Code Style

- **ui**: Reorganize imports and improve code formatting in MainWindow class
  ([`bb158e3`](https://github.com/samzong/hf-model-downloader/commit/bb158e34e36a8aecf8664b192b153a8da2fa8cd1))

### Refactoring

- **build**: Improve build.py formatting and architecture detection logic
  ([`efaeb53`](https://github.com/samzong/hf-model-downloader/commit/efaeb530c569caea7f5197288677854a67f9f23e))

- **downloader**: Update deprecated classes and functions to use UnifiedDownloadWorker and
  unified_download_model
  ([`85e420f`](https://github.com/samzong/hf-model-downloader/commit/85e420f2db954912457f7423381dc17520a311b6))

- **icon_generator**: Reorganize imports and improve image processing functions readability
  ([`4de6685`](https://github.com/samzong/hf-model-downloader/commit/4de6685e0a4aba8846acf864c4e9f6a557c78086))

- **main**: Improve multiprocessing setup and env handling for PyQt app
  ([`1018c68`](https://github.com/samzong/hf-model-downloader/commit/1018c68d58532a20d4ed313df406d781c5cc8aca))

### Testing

- **tests**: Add basic end-to-end tests for huggingface and modelscope downloads with PyQt event
  loop
  ([`7975446`](https://github.com/samzong/hf-model-downloader/commit/797544657ad8632874bfe01f9e95b3ce7a1ed8f1))


## v0.5.0 (2025-08-20)

### Features

- **downloader**: Add dataset support using MsDataset in ModelScope downloader
  ([`a5ff19f`](https://github.com/samzong/hf-model-downloader/commit/a5ff19fd93d5ad9e31ecbbecf163cb77f6e37178))

### Refactoring

- **download**: Improve ModelScope download with authentication and error handling
  ([`9f0fc6b`](https://github.com/samzong/hf-model-downloader/commit/9f0fc6b921146db43fd6e8b176577ed4d19e0fd2))

- **ui, unified_downloader**: Enhance download worker cleanup and thread safety
  ([`b1c6331`](https://github.com/samzong/hf-model-downloader/commit/b1c6331472b24b1ab3830678532205ccaaf42296))


## v0.4.0 (2025-08-20)

### Features

- **downloader**: Add backward compatibility wrapper and unify downloaders
  ([`953a329`](https://github.com/samzong/hf-model-downloader/commit/953a3290cd8fe24d1b2eecec00decfa4e9ffd1a1))


## v0.3.3 (2025-08-19)

### Refactoring

- **build**: Replace Windows installer with zip package and update workflow upload script
  ([`a7fdccd`](https://github.com/samzong/hf-model-downloader/commit/a7fdccdaa0cd75b3ab11e7dfd1b94f4662048e9e))


## v0.3.2 (2025-08-19)

### Chores

- **ci**: Prioritize GH_PAT secret and add debug checks in workflows and scripts
  ([`714294a`](https://github.com/samzong/hf-model-downloader/commit/714294a8821f60d9c6c20e96b7a469da23a25521))


## v0.3.1 (2025-08-19)

### Chores

- **workflows**: Update token from GH_TOKEN to GH_PAT for release authentication
  ([`809ed88`](https://github.com/samzong/hf-model-downloader/commit/809ed8883b1efca2941d8bdc5ef64d5e2168199d))


## v0.3.0 (2025-08-19)

### Features

- Improve workflow trigger mechanism
  ([`3df93a1`](https://github.com/samzong/hf-model-downloader/commit/3df93a1bf720e5063d8d7bf2e1dda1fec36a6a5d))


## v0.2.0 (2025-08-19)

### Bug Fixes

- **makefile**: Correct dmg filename and export VERSION for homebrew update script
  ([`f0e94f7`](https://github.com/samzong/hf-model-downloader/commit/f0e94f77bfe0e149261e6c0b598934b9704bcc59))

### Features

- **ci**: Add multi-platform build and release workflows with macOS and Windows support
  ([`e9f560f`](https://github.com/samzong/hf-model-downloader/commit/e9f560f3516c3525a70d39c525458d1d19d1ec6d))


## v0.1.1 (2025-08-19)

### Chores

- **ci**: Add debug info to release workflow and improve homebrew update script handling
  ([`8d35874`](https://github.com/samzong/hf-model-downloader/commit/8d35874a986c9a3b823a0fbdd8dd7231f614fea8))


## v0.1.0 (2025-08-18)

### Bug Fixes

- **build**: Correct Makefile syntax errors in define blocks
  ([`139886f`](https://github.com/samzong/hf-model-downloader/commit/139886f7093d2637deec281fa6c00f602f46f9a4))

### Build System

- **release**: Intergrate python-semantic-release
  ([`f64b7ef`](https://github.com/samzong/hf-model-downloader/commit/f64b7efcd1a52bfd5de303cbb29064602a58d063))

### Features

- **homebrew**: Add modular script and Makefile check for Homebrew Cask update
  ([`2f9c902`](https://github.com/samzong/hf-model-downloader/commit/2f9c902080686e01d5155d0a9db2f2bb77f99362))

### Refactoring

- **ci**: Enhance release workflow to output version and release status
  ([`7889dcf`](https://github.com/samzong/hf-model-downloader/commit/7889dcfdcf9f20b5cc97ca84e841330b75a23a51))

- **makefile**: Improve maintainability with enhanced logging, validations, and organized variables
  ([`d6c4372`](https://github.com/samzong/hf-model-downloader/commit/d6c43722647c0d2f4c51310a927bd2ccb9118928))


## v0.0.7 (2025-08-18)

### Documentation

- **license**: Add initial MIT license file
  ([`4cac811`](https://github.com/samzong/hf-model-downloader/commit/4cac811b63f014ea47eb40bcb4d38872ea164a9d))

### Features

- **python**: Add environment config, python 3.13, and dependencies for HF model downloader
  ([`c8d7975`](https://github.com/samzong/hf-model-downloader/commit/c8d79752f7b851002ecb3a55d3f3042ec3a4382e))

### Refactoring

- **downloader**: Add LoggerManager to unify log handler management and prevent leaks
  ([`ca6ac84`](https://github.com/samzong/hf-model-downloader/commit/ca6ac841ed7e2fe0095eefdb6775766192f09e5a))

- **Makefile**: Update SHA256 handling for Homebrew Cask to use new on_arm/on_intel format
  ([`f7d8cc4`](https://github.com/samzong/hf-model-downloader/commit/f7d8cc448b581457d993492a362b976bf560e270))


## v0.0.6 (2025-06-11)


## v0.0.5 (2025-06-11)

### Bug Fixes

- Use architecture-specific executable name for Windows builds
  ([`25cdcc8`](https://github.com/samzong/hf-model-downloader/commit/25cdcc8aef10a7e2514cba6ced82347845fe3b3b))

### Documentation

- **claimed**: Add CLAUDE.md with development and architecture guidance
  ([`0e9a596`](https://github.com/samzong/hf-model-downloader/commit/0e9a5964763203c0c0793a79e711f1f75c7e34a8))

- **readme**: Add DeepWiki badge link to project header
  ([`a047f5e`](https://github.com/samzong/hf-model-downloader/commit/a047f5eff556c299f8203b5f6c5fea8f65b85b60))


## v0.0.4 (2025-03-05)


## v0.0.2 (2025-01-16)


## v0.0.1 (2025-01-15)

- Initial Release
