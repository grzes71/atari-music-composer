# "Vaults of Nhyrmeth" — the Music DSL example from docs/music_dsl.md §4, verbatim.
#
# This is an existing composition: it is not written for the profile integration and it
# contains nothing about POKEY profiles. The binding lives in a separate file
# (vaults_binding.json); the composition is untouched. `BASS 16BIT` makes channel 1 the
# low byte of a joined pair, which is the layout an archaeology PAIR profile realizes.
TITLE "Vaults of Nhyrmeth"
AUTHOR "AI Composer"
KEY D
MODE MINOR
BPM 90
CHANNELS 4
BASS 16BIT
LOOP 0

SEQUENCE A1 A2 B1 B2 A1 A2

[PATTERN A1 role=theme]
CH1 BASS V14
D2/8 F2/8 C2/8 D2/8 A2/8 Bb2/8 A2/8 D2/8

CH3 LEAD V13
D4/4 F4/4 A4/6 G4/2 F4/4 E4/4 D4/8

CH4 PERC V10
C4/2 R/2 C4/2 R/2 C4/4 R/4 C4/2 R/2 C4/2 R/2 C4/4 R/4

[PATTERN A2 role=theme]
CH1 BASS V14
D2/8 F2/8 C2/8 D2/8 Bb2/8 C3/8 A2/8 D2/8

CH3 LEAD V13
D4/4 F4/4 A4/4 D5/4 C5/4 Bb4/4 A4/8

CH4 PERC V10
C4/2 R/2 C4/2 R/2 C4/4 R/4 C4/2 R/2 C4/2 R/2 C4/4 R/4

[PATTERN B1 role=contrast]
CH1 BASS V14
G2/8 Bb2/8 F2/8 G2/8 D2/8 F2/8 C2/8 G2/8

CH3 LEAD V13
G4/4 Bb4/4 D5/4 G5/4 F5/4 D5/4 C5/8

CH4 PERC V10
C4/2 R/2 C4/2 R/2 C4/4 R/4 C4/2 R/2 C4/2 R/2 C4/4 R/4

[PATTERN B2 role=contrast]
CH1 BASS V14
A2/8 C3/8 G2/8 A2/8 F2/8 G2/8 E2/8 D2/8

CH3 LEAD V13
A4/4 C5/4 E5/4 A5/4 G5/4 E5/4 D5/8

CH4 PERC V10
C4/2 R/2 C4/2 R/2 C4/4 R/4 C4/2 R/2 C4/2 R/2 C4/4 R/4
