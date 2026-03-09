# ADA & WCAG Compliance Standards Reference

## WCAG 2.1 Conformance Levels

| Level | Description                                          |
|-------|------------------------------------------------------|
| A     | Minimum accessibility — essential barriers removed   |
| AA    | Standard compliance — required by most laws          |
| AAA   | Highest level — aspirational, not always achievable  |

## POUR Principles

### 1. Perceivable

| Criterion | Level | Requirement                                                |
|-----------|-------|------------------------------------------------------------|
| 1.1.1     | A     | Non-text content has text alternatives                     |
| 1.2.1     | A     | Audio/video has captions or transcript                     |
| 1.2.2     | A     | Synchronized captions for video                            |
| 1.2.3     | A     | Audio description or media alternative                     |
| 1.2.5     | AA    | Audio description for prerecorded video                    |
| 1.3.1     | A     | Info and relationships conveyed through structure           |
| 1.3.2     | A     | Meaningful reading sequence preserved                      |
| 1.3.3     | A     | Instructions don't rely solely on sensory characteristics  |
| 1.3.4     | AA    | Content doesn't restrict orientation                       |
| 1.3.5     | AA    | Input purpose can be programmatically determined           |
| 1.4.1     | A     | Color is not the only visual means of conveying info       |
| 1.4.2     | A     | Audio control — pause, stop, or adjust volume              |
| 1.4.3     | AA    | Contrast ratio at least 4.5:1 (normal) / 3:1 (large)      |
| 1.4.4     | AA    | Text resizable up to 200% without loss of functionality    |
| 1.4.5     | AA    | Images of text avoided where possible                      |
| 1.4.10    | AA    | Content reflows without horizontal scrolling at 320px      |
| 1.4.11    | AA    | Non-text contrast at least 3:1                             |
| 1.4.12    | AA    | Text spacing adjustable without loss of content            |
| 1.4.13    | AA    | Content on hover/focus dismissible, hoverable, persistent  |

### 2. Operable

| Criterion | Level | Requirement                                                |
|-----------|-------|------------------------------------------------------------|
| 2.1.1     | A     | All functionality available from keyboard                  |
| 2.1.2     | A     | No keyboard trap                                           |
| 2.1.4     | A     | Character key shortcuts can be remapped or disabled        |
| 2.2.1     | A     | Timing adjustable for time-limited content                 |
| 2.2.2     | A     | Moving content can be paused, stopped, or hidden           |
| 2.3.1     | A     | No content flashes more than 3 times per second            |
| 2.4.1     | A     | Skip navigation mechanism                                  |
| 2.4.2     | A     | Pages have descriptive titles                              |
| 2.4.3     | A     | Focus order is logical and meaningful                      |
| 2.4.4     | A     | Link purpose determinable from text or context             |
| 2.4.5     | AA    | Multiple ways to locate pages (nav, search, sitemap)       |
| 2.4.6     | AA    | Headings and labels are descriptive                        |
| 2.4.7     | AA    | Focus indicator visible                                    |
| 2.5.1     | A     | Pointer gestures have single-pointer alternative           |
| 2.5.2     | A     | Pointer cancellation supported (up-event activation)       |
| 2.5.3     | A     | Accessible name matches visible label                      |
| 2.5.4     | A     | Motion-activated functions have UI alternative             |

### 3. Understandable

| Criterion | Level | Requirement                                                |
|-----------|-------|------------------------------------------------------------|
| 3.1.1     | A     | Language of page identified (lang attribute)               |
| 3.1.2     | AA    | Language of parts identified where different               |
| 3.2.1     | A     | No unexpected context change on focus                      |
| 3.2.2     | A     | No unexpected context change on input                      |
| 3.2.3     | AA    | Consistent navigation across pages                         |
| 3.2.4     | AA    | Consistent identification of components                    |
| 3.3.1     | A     | Input errors identified and described                      |
| 3.3.2     | A     | Labels or instructions provided for input                  |
| 3.3.3     | AA    | Error suggestions provided                                 |
| 3.3.4     | AA    | Error prevention for legal/financial submissions           |

### 4. Robust

| Criterion | Level | Requirement                                                |
|-----------|-------|------------------------------------------------------------|
| 4.1.1     | A     | Valid HTML (no duplicate IDs, proper nesting)              |
| 4.1.2     | A     | Name, role, value for all UI components                    |
| 4.1.3     | AA    | Status messages use ARIA live regions                      |

## Common Framework Patterns

### React / Next.js
- Use semantic HTML elements (`<nav>`, `<main>`, `<article>`)
- `aria-*` props on custom components
- `role` attributes where semantic HTML isn't sufficient
- `tabIndex` for focus management
- `useRef` + `focus()` for programmatic focus
- `aria-live` regions for dynamic content updates

### HTML / CSS
- `<label for="id">` for all form inputs
- `<fieldset>` + `<legend>` for related form groups
- `alt=""` for decorative images (empty alt, not missing alt)
- `prefers-reduced-motion` media query for animations
- `:focus-visible` styles for keyboard focus indicators
- `min-height: 44px; min-width: 44px` for touch targets

## Severity Mapping

| WCAG Level | Default Severity | Rationale                           |
|------------|------------------|-------------------------------------|
| A          | Critical/High    | Basic accessibility — legal risk    |
| AA         | High/Medium      | Standard compliance requirement     |
| AAA        | Low/Info         | Aspirational — best practice        |
