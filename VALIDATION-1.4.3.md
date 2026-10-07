# Sergек 1.4.3 — three-language interface validation

Date: 7 October 2026. Windows x64. This release adds Kazakh, Russian and English interface selection.

- 416 interface messages cover student and teacher pages, forms, event labels, statuses, startup progress and common errors.
- Browser preferences use localStorage. The desktop application additionally saves a validated language code in its stable data directory, independently of the random localhost port.
- Language changes do not reload the LMS, reset a form, restart camera capture or interrupt an exam. Names, answers, comments and LMS course content remain original data.
- PDF exports accept `lang=kk|ru|en`; omitted language remains Kazakh. Invalid language codes return HTTP 422. JSON audit keys and records remain unchanged.

## Executed checks

| Check | Result |
|---|---|
| Python suite | 67 passed; includes report translations and original security/session tests |
| API and report suite after endpoint assertions | 29 passed; three PDF languages and invalid-code rejection |
| Desktop rule and startup transaction tests | 13 passed |
| Browser acceptance | 6 passed; language persistence, translated errors, preserved password/comment/profile input and report links |
| Real Electron application | Language changes during an active software exam preserve session ID and selected answer; submission completes |
| Packaged Windows application | Same acceptance passed with `release-v1.4.3/win-unpacked/Sergek Proctor.exe` |
| Restart with a different backend port | Selected English persisted across restart |
| Invalid desktop language | Rejected without changing saved selection |
| Native guard self-checks | 5 policy checks and 10 own-process window checks passed |
| Production UI | TypeScript and Vite build succeeded |

Machine-readable Electron result: [tests/languages-v143.json](tests/languages-v143.json).
Browser and desktop screenshots were visually checked; three localized sample PDF reports were rendered for layout inspection.

Camera, microphone and OS restrictions are disabled only in the administrator's software acceptance fixture. These checks establish interface and session behavior; they do not establish new physical phone-detection, identity-resistance or USB enforcement measurements. Earlier physical and load measurements remain documented in [VALIDATION-1.4.2.md](VALIDATION-1.4.2.md) and [VALIDATION-1.4.0.md](VALIDATION-1.4.0.md).
