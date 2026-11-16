---
name: ui
description: Implement or modify Baton user interfaces using Django Templates, semantic HTML and minimal CSS. Apply to pages, layouts, forms and static assets, with attention to mobile usability, accessibility and fast loading.
---

# Baton UI

Build simple, optimized interfaces that serve the approved requirements. Inspect
the existing templates and styles before editing, and reuse the base template
and established visual conventions.

## Implementation principles

1. Prefer simplicity over decoration. Give each page a clear purpose and avoid
   visual elements that do not support it.
2. Start with a mobile layout, then adapt to larger screens. Use flexible widths
   and allow content to wrap without horizontal scrolling.
3. Keep CSS and JavaScript minimal. Add JavaScript only when the required
   interaction warrants it.
4. Use Django-rendered HTML as the default and extend the reusable base template.
5. Make core functionality work without JavaScript, including navigation and
   form submission. Validate and authorize submitted data on the server.
6. Prefer system fonts and existing assets. Avoid unnecessary external fonts,
   icon libraries, animation libraries and frontend frameworks.
7. Optimize images and static assets. Choose suitable formats and dimensions,
   set image width and height, and lazy-load images below the initial viewport
   when appropriate. Serve assets through Django's static file conventions.
8. Use semantic HTML and accessible forms: meaningful landmarks and heading
   order, visible labels, appropriate input types, associated error messages,
   keyboard access and visible focus states.
9. Maintain consistent spacing, typography, colors and interaction patterns.
   Reuse existing styles without creating speculative abstractions.
10. Prioritize fast loading on slow connections and usability on small screens.
    Keep initial asset requests and page weight low.
11. Avoid excessive nesting, unnecessary wrappers and component abstractions.
    Add structure only when layout or semantics requires it.
12. Do not introduce a design system or UI framework unless actual project
    requirements justify it within the authorized scope.

## Completion checklist

- [ ] The interface implements the approved requirements and all visible links
      and controls perform their intended actions.
- [ ] Pages extend the base template and use semantic landmarks, a descriptive
      page title and a logical heading order.
- [ ] Layout works at small mobile widths and larger sizes; text remains usable
      at 200% zoom without clipping or horizontal scrolling.
- [ ] Navigation and any forms work without JavaScript.
- [ ] Keyboard navigation is usable; focus is visible, contrast is sufficient,
      and interactive targets are large enough for touch.
- [ ] Any forms have labels, instructions and accessible errors, with server-side
      validation, authorization and CSRF protection where applicable.
- [ ] Images have appropriate alternative text and explicit dimensions; assets
      are optimized and there are no unnecessary external requests.
- [ ] Styles follow existing spacing, typography, colors and interaction patterns
      without unnecessary wrappers, libraries or duplicated rules.
- [ ] Verify the rendered page and relevant routes, execute relevant tests and
      Django checks, and confirm static asset discovery and delivery.
- [ ] Report what was verified and any limits, including browser or accessibility
      checks that were not performed.
