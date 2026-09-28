# CHANGELOG


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
