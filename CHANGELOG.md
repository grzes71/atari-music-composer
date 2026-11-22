# CHANGELOG


## v0.19.0 (2026-11-22)

### Features

- **instruments**: Integrate cmc+ open hi-hat, kick stopa, and low tom
  ([`4dc295d`](https://github.com/grzes71/atari-music-composer/commit/4dc295de8d7e0a30e78df8e77121baa40545ce9b))


## v0.18.0 (2026-11-22)

### Features

- **percussion**: Integrate rhytmizer_closed_hihat and make it default for v2
  ([`19f2d36`](https://github.com/grzes71/atari-music-composer/commit/19f2d36bbfb377ea746fd45416d585fb6abd5e11))

- **studio**: Export companion .arrangement.json manifest with XEX
  ([`f98f354`](https://github.com/grzes71/atari-music-composer/commit/f98f354ed7f6394f90a3616b24325705b069c9c1))


## v0.17.1 (2026-11-19)

### Bug Fixes

- **instruments**: Switch lead_c1_octave_pulse from $40 to $A0 pure tone
  ([`7a39b33`](https://github.com/grzes71/atari-music-composer/commit/7a39b332b89ae886214bf21327e64da6e257c7b5))


## v0.17.0 (2026-11-19)

### Features

- **xex-v2**: Promote runtime contracts, fix harness VU meter, and add py65/Altirra XEX verification
  ([`6fe935c`](https://github.com/grzes71/atari-music-composer/commit/6fe935cf8d5a4f3c6b2e6b7b27d40abd24a6dcef))


## v0.16.0 (2026-11-18)

### Features

- **studio**: Add presets, A/B comparison, PCM playback, and tabbed UI
  ([`812923e`](https://github.com/grzes71/atari-music-composer/commit/812923e094e36019757f50fa2d16ddec75b4a9e5))


## v0.15.0 (2026-11-18)

### Features

- **ai**: Add rhythmic density control and separate perc/echo role analysis
  ([`5130a92`](https://github.com/grzes71/atari-music-composer/commit/5130a923f2778b1440e81b6c18c01ba43f363245))


## v0.14.0 (2026-11-18)

### Features

- **studio**: Add Atari XEX export workflow with safe transactional commit
  ([`a79ea63`](https://github.com/grzes71/atari-music-composer/commit/a79ea63431824214fad9b95ef1b5871631d6d346))


## v0.13.0 (2026-11-18)

### Features

- **studio**: Implement Phase 1 instrument explorer GUI and headless backend
  ([`7f05e2f`](https://github.com/grzes71/atari-music-composer/commit/7f05e2f2279b3a49c6b43b29d8fefeeafd0d6101))


## v0.12.0 (2026-11-17)

### Bug Fixes

- **tests**: Register ai/prompt_library and ai/critique in CORE_MODULES
  ([`c513ce5`](https://github.com/grzes71/atari-music-composer/commit/c513ce530b49708b093846bcf7fbbc4f3a21a945))

### Features

- **ai**: Add rich prompt profile, pre-composition brief, and critique loop
  ([`4fb5e20`](https://github.com/grzes71/atari-music-composer/commit/4fb5e209ec425f95fe70d88121cde3f22bc05ad2))


## v0.11.1 (2026-11-17)

### Bug Fixes

- **skill**: Add required YAML frontmatter to SKILL.md
  ([`5261803`](https://github.com/grzes71/atari-music-composer/commit/5261803c86073d67a26a42444b9691a5261c0c17))

### Documentation

- **skill**: Document SSOT instrument catalog, arrange, and generate_arrangements.py
  ([`ec275cd`](https://github.com/grzes71/atari-music-composer/commit/ec275cd789b54bcd6894ecf99fe4ac6ec3f2b954))


## v0.11.0 (2026-11-17)

### Features

- **scripts**: Replace PowerShell batch scripts with adaptive generate_arrangements.py
  ([`05fd9bf`](https://github.com/grzes71/atari-music-composer/commit/05fd9bfa8588209f57f1dfea695100a4ee02ed9f))


## v0.10.0 (2026-11-16)

### Features

- **scripts**: Use atari-music.exe, add vanilla v1 variant, and track HISTORY.md
  ([`ee1d6ac`](https://github.com/grzes71/atari-music-composer/commit/ee1d6acbaac3b8f565d8e4fe10246d770a338624))


## v0.9.1 (2026-11-16)

### Bug Fixes

- **scripts**: Resolve relative -OutputDirectory against PowerShell location
  ([`2239a32`](https://github.com/grzes71/atari-music-composer/commit/2239a32cc617c3b5ea8c1977c8ac273f551e2006))


## v0.9.0 (2026-11-16)

### Bug Fixes

- Align POLY4 and POLY5 timing with POKEY hardware
  ([`920e406`](https://github.com/grzes71/atari-music-composer/commit/920e406135a756b2e2147a32f77c26cc93614046))

- Enforce instrument divider and AUDCTL consistency
  ([`4b7eaa6`](https://github.com/grzes71/atari-music-composer/commit/4b7eaa6dc74f21e659e26ad65ee442e4264baa7b))

- **audio**: Resolve POKEY ADSR envelope timing and channel muting
  ([`0abc06e`](https://github.com/grzes71/atari-music-composer/commit/0abc06efb6cb759b1ef116f6cdaf8dcd54feafd4))

- **ci,tests**: Unignore core fixtures and align release workflow with core suite
  ([`6f277f4`](https://github.com/grzes71/atari-music-composer/commit/6f277f4b198e383df831ea423f0d4696892c1e84))

- **ir,exporter**: Preserve Composer v4 v1 export and harden v2 stream bounds
  ([`cbb9419`](https://github.com/grzes71/atari-music-composer/commit/cbb94194b660f76b95f7c86b6e5fb55326467b23))

### Documentation

- **readme**: Document Stages A-E instrument system, arrangement workflow, and current CLI
  ([`742e014`](https://github.com/grzes71/atari-music-composer/commit/742e01467a5c474a05a7496f75b894f1f03fc369))

- **stage-c**: Add SONG_FORMAT_V2 specification and update HISTORY.md
  ([`c73e381`](https://github.com/grzes71/atari-music-composer/commit/c73e3818ffed8106d9111499adece9f191dee9d9))

### Features

- Implement instrument catalog and POKEY runtime foundation
  ([`2bf8c1f`](https://github.com/grzes71/atari-music-composer/commit/2bf8c1fa47a036974200eb96b4ffd92c64b0ad69))

- Improve POKEY hardware-accurate WAV synthesis
  ([`0cd82e0`](https://github.com/grzes71/atari-music-composer/commit/0cd82e038063e3b8ecf43b51cff776371b254796))

- **ai**: Integrate SSOT instrument catalog and runtime validation into AI generator
  ([`2d23bdb`](https://github.com/grzes71/atari-music-composer/commit/2d23bdb87b810703ba8f91fcae603e7871c4b0de))

- **cli,tests**: Add arrange CLI command and Stage E arrangement pipeline tests
  ([`821bf09`](https://github.com/grzes71/atari-music-composer/commit/821bf096462665f967dc5a09de1157fcd6a28f17))

- **cli,tests**: Add catalog CLI commands, v2 options, and Stage D tests
  ([`4f71fe9`](https://github.com/grzes71/atari-music-composer/commit/4f71fe9e919c1f66e2322a42a07074d963bc8a52))

- **composer,api**: Add opt-in catalog instruments and PROGRAM_CHANGE to Composer v4
  ([`6b3aa84`](https://github.com/grzes71/atari-music-composer/commit/6b3aa84b8c461b7f298b3e01651cd9871c8d2b36))

- **exporter**: Add SONG_FORMAT_VERSION=2 SoA export and stream validation
  ([`2098bd0`](https://github.com/grzes71/atari-music-composer/commit/2098bd07c5210599c9266cd9ebc884fb6af6d3c4))

- **instruments**: Add CORE channel instrument planner and v1/v2 format resolver
  ([`f8c65d9`](https://github.com/grzes71/atari-music-composer/commit/f8c65d9694b5534b5928c88948c5ccee7deac94e))

- **instruments,api,ai**: Add decoupled arrange_song, composition fingerprint, and shared XEX
  builder
  ([`2ee6254`](https://github.com/grzes71/atari-music-composer/commit/2ee625433bd2e7cc606f1fc48b1487aa1b9c3cdd))

- **ir**: Add v2 multi-instrument, macro, and pitch envelope IR models
  ([`18b1075`](https://github.com/grzes71/atari-music-composer/commit/18b1075bcba3c7e2f6e97d5ac35f55f37bdd238e))

- **player**: Add SONG_FORMAT_VERSION=2 dispatch, SoA loader, and PROGRAM_CHANGE
  ([`1015e95`](https://github.com/grzes71/atari-music-composer/commit/1015e95f99791dee1d2b8e40b185f8ce34a70d03))

- **player**: Add Transient Macro Engine and Pitch Envelope to player.asm
  ([`6751ffd`](https://github.com/grzes71/atari-music-composer/commit/6751ffd10e4a0c3efbc233a3e7f1acbfcf89cc17))

- **scripts**: Add 8-bit and 16-bit PowerShell batch arrangement scripts
  ([`2ba9c06`](https://github.com/grzes71/atari-music-composer/commit/2ba9c06f928b934f0d884845fce76f2c38a41136))

- **scripts**: Add automatic Music DSL to JSON conversion in batch scripts
  ([`6f633ff`](https://github.com/grzes71/atari-music-composer/commit/6f633ff3996a933437b87b794e63e16de6e9e119))

- **scripts,tests**: Add automated instrument test suite generator
  ([`6d64327`](https://github.com/grzes71/atari-music-composer/commit/6d643277c3bbe31bdc4c546cf255a3ea3e00acc6))

### Refactoring

- Isolate CORE boundaries and classify pytest profiles
  ([`dcbb009`](https://github.com/grzes71/atari-music-composer/commit/dcbb00926ae63f041ee2158428ec2eedcfc02793))

### Testing

- Harden architecture boundary checks
  ([`d25d5b0`](https://github.com/grzes71/atari-music-composer/commit/d25d5b024ceeeef62716869b344000883ba2279d))

- **stage-c**: Add Python frame oracle, py65 parity, and ASAP 8.0.0 v2 suite
  ([`7f4da84`](https://github.com/grzes71/atari-music-composer/commit/7f4da8466a94d56221565e973ad6cd5ea988696f))


## v0.8.0 (2026-09-29)

### Features

- **logging**: Add debug logging for Music DSL prompts, payloads, and responses
  ([`8b5e214`](https://github.com/grzes71/atari-music-composer/commit/8b5e214d5c4ec9149e7c5fe6d2e42738e6c25890))


## v0.7.0 (2026-09-29)

### Bug Fixes

- **test**: Use require_local_artifact for gitignored examples and add embedded equivalence test
  ([`e5bf009`](https://github.com/grzes71/atari-music-composer/commit/e5bf0098e9a8abad7d0001c89468b5db27cea5b6))

### Features

- **dsl**: Implement Music DSL v1.1 with inferred pattern length and regression benchmark
  ([`dc4b016`](https://github.com/grzes71/atari-music-composer/commit/dc4b016dcb27c41c7e88c685e6c6484f231de147))


## v0.6.0 (2026-09-29)

### Features

- **dsl**: Implement compact music dsl, split import commands, and add benchmark suite
  ([`08719c8`](https://github.com/grzes71/atari-music-composer/commit/08719c86d2ef50c5b119c7507e56f4deaf852726))


## v0.5.5 (2026-09-29)

### Bug Fixes

- **xex**: Correct keyboard scancodes for channel muting keys 1-4
  ([`fc86707`](https://github.com/grzes71/atari-music-composer/commit/fc86707579eecb1b153e4fe135b32f35c7cb4463))


## v0.5.4 (2026-09-28)

### Bug Fixes

- **pokey**: Address audit findings F-1 to F-7 across synthesis and export
  ([`22fe9fa`](https://github.com/grzes71/atari-music-composer/commit/22fe9fa7063fecd8fa207ab28f820f3655220d34))


## v0.5.3 (2026-09-28)

### Bug Fixes

- **export**: Align MADS assembly exporter with POKEY IR and WAV renderer
  ([`e098a2c`](https://github.com/grzes71/atari-music-composer/commit/e098a2c1f6a5b8023cba50ea5d527f9728128fdf))


## v0.5.2 (2026-09-28)

### Bug Fixes

- **synth**: Implement accurate audf-clocked lfsr noise synthesis
  ([`e0b0924`](https://github.com/grzes71/atari-music-composer/commit/e0b09247295d5c567f01919a9eed0d9c0fc4902f))


## v0.5.1 (2026-09-28)

### Bug Fixes

- **release**: Synchronize package version tracking in init and semantic-release
  ([`c740cf0`](https://github.com/grzes71/atari-music-composer/commit/c740cf0497c0aa0d7001c2029f65926df38fbbb6))


## v0.5.0 (2026-09-28)

### Features

- **visualizer**: Add interactive channel muting keys 1-4 and dark green theme
  ([`6ebf55e`](https://github.com/grzes71/atari-music-composer/commit/6ebf55e7a15bb45269f62c9a7e2e75fc8333719e))


## v0.4.0 (2026-09-28)

### Features

- **ai**: Parse server retry delay on 429 and add -v cli flag
  ([`09de6cc`](https://github.com/grzes71/atari-music-composer/commit/09de6cc61bcc8b531cca32f6a94c500e32e3ea7c))


## v0.3.1 (2026-09-28)

### Bug Fixes

- **ai**: Add exponential backoff for transient 503 and 429 errors
  ([`accead5`](https://github.com/grzes71/atari-music-composer/commit/accead56f3e221a07ff23e43c1f1d190729febf3))


## v0.3.0 (2026-09-28)

### Features

- **cli**: Refactor AI configuration, add --env-file and provider overrides
  ([`f132fee`](https://github.com/grzes71/atari-music-composer/commit/f132fee49c6005fb73604b7e91f915df5b9bc0c5))

### Refactoring

- **prompts**: Revise ai composer system prompt for musical freedom and channel economics
  ([`4e3a277`](https://github.com/grzes71/atari-music-composer/commit/4e3a2777d31346470e846cbbebdd041f3434d435))


## v0.2.1 (2026-09-27)

### Bug Fixes

- **client**: Import missing subprocess module for build-xex
  ([`e50710c`](https://github.com/grzes71/atari-music-composer/commit/e50710c2f4963575403788f510e5feda7c5b7f25))


## v0.2.0 (2026-09-27)

### Features

- **cli**: Add player.asm path option and working directory lookup
  ([`4a42d2f`](https://github.com/grzes71/atari-music-composer/commit/4a42d2fb5fa4222b81ed2c0a0541a5d4d0c02fb8))


## v0.1.1 (2026-09-27)

### Bug Fixes

- **cli**: Streamline public commands and implement composition analyze command
  ([`4d0aa5f`](https://github.com/grzes71/atari-music-composer/commit/4d0aa5f43bd9d124d5874110dfd7d02d4835d29f))


## v0.1.0 (2026-09-27)

### Bug Fixes

- **ci**: Align release workflow and pyproject.toml branch with main
  ([`0cb4520`](https://github.com/grzes71/atari-music-composer/commit/0cb45204711b70284c50942426ae8e83a6edc260))

- **deps**: Add python-dotenv to pyproject.toml dependencies
  ([`5cc0379`](https://github.com/grzes71/atari-music-composer/commit/5cc0379cb9de5ec063a560419edfa6b67b1fa2d3))

### Continuous Integration

- **release**: Update python version to 3.14
  ([`0b34c6c`](https://github.com/grzes71/atari-music-composer/commit/0b34c6cd88b84286eee48f5b848caefe17ede82d))

### Features

- **logging**: Add central logging, secret masking, stream separation, and agent skill reference
  ([`7a5e421`](https://github.com/grzes71/atari-music-composer/commit/7a5e421e6b909cb9382514951f350cf5831f2020))
