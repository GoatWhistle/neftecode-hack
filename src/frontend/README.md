# src/frontend

React + TypeScript + CSS. Сборка: `npm install`, затем `npm run build` → `src/frontend/dist/`.

Python отдаёт собранную статику по пути из параметра `--static` (умолчание `src/frontend/dist`).
Внутрь `src/neftecode` ни исходники, ни сборка не попадают.

Ограничение: ни одной внешней ссылки в рантайме — шрифты системные, графика инлайн-SVG.
