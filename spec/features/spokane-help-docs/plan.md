# Execution Plan: Spokane Deep Dive in Help Docs

| Task | Agent | Status |
|---|---|---|
| Embed accessible episodes below the overview video | `ui` | done |
| Remove separate navigation and use Introduction anchors | `ui` | done |
| Validate inline placement, navigation, media errors, and build | `ui-validation` | done |
| Add lightweight previews to all seven existing help videos | `ui` | done |
| Validate legacy poster coverage and preview rendering | `ui-validation` | done |
| Allow hosted recordings, captions, and posters in the deployed CSP | `ui` | done |
| Validate CSP asset permissions and preserve default/script restrictions | `ui-validation` | done |

## Deployed CSP Validation

Commands run from `ui/`:

- `node --test src\Components\HelpDocs\spokaneDeepDive.test.js src\Components\HelpDocs\videoPosters.test.js`: 8 tests passed.
- `npx eslint src\Components\HelpDocs\spokaneDeepDive.test.js --max-warnings 0`: passed.
- `npm run build`: passed.

The regression test checks CSP permissions for all 18 hosted episode assets
and requires the exact Spokane directory source with a trailing slash instead
of a host-wide permission. It retains local media access and verifies unchanged
default and script source restrictions. Production playback on Azure Static
Web Apps has not been tested.

## Legacy Video Preview Validation

Commands run from `ui/`:

- `node --test src\Components\HelpDocs\spokaneDeepDive.test.js src\Components\HelpDocs\videoPosters.test.js`: 7 tests passed.
- `npx eslint src\Components\HelpDocs\HelpDocsOverview.jsx src\Components\HelpDocs\HelpDocsProjects.jsx src\Components\HelpDocs\HelpDocsImageLayers.jsx src\Components\HelpDocs\videoPosters.test.js --max-warnings 0`: passed.
- `npm run build`: passed.

Playwright loaded every local poster in Overview (1), Projects (3), and Image
Layers (3). All seven images decoded at 1280 x 720; every recording remained
paused with `readyState=0`, confirming that previews do not preload videos.
JPEG files are smaller than 64 KiB each. The extracted title frames were
visually checked for Overview and the project/image-layer creation videos.

## Introduction Placement Validation

The same Node test, targeted ESLint, and production build commands below passed
again after relocation.

Playwright verified seven total videos in Introduction: the existing overview
recording followed immediately by all six Spokane episodes. The series uses an
H2 and six H3 headings with unique IDs, and no separate desktop navigation group
remains. A source error still displays the episode alert. At a 390 px mobile
viewport, all six videos and English caption tracks render without horizontal
overflow. The new direct episode anchor resolves within Overview.

Mobile dropdown interaction could not be revalidated: the browser automation
timed out waiting for click stability. The rendered dropdown and its existing
navigation component remain unchanged; the separate Spokane entries were
removed from the shared navigation data.

## Previous Validation Evidence

Commands run from `ui/`:

- `node --test src/Components/HelpDocs/spokaneDeepDive.test.js`: 4 tests passed.
- `npx eslint src/Components/HelpDocs.jsx src/Components/HelpDocs/HelpDocsOverview.jsx src/Components/HelpDocs/HelpDocsSpokaneDeepDive.jsx src/Components/HelpDocs/spokaneDeepDiveEpisodes.js src/Components/HelpDocs/spokaneDeepDive.test.js --max-warnings 0`: passed.
- `npm run build`: passed.

Before relocation into Introduction, Playwright checks ran against the real Help Docs components in an isolated
preview, without authentication or backend requests. Desktop navigation,
overview entry, existing Projects content, browser back, direct episode reload,
mobile selection, visible episode headings, and no horizontal overflow passed.
All six rendered players matched the expected controls, previews, caption
tracks, and fallback links. A source error displayed the episode alert.
Introduction playback advanced and loaded 9 English caption cues. All 18 hosted
media assets returned HTTP 200 to cross-origin HEAD requests.
