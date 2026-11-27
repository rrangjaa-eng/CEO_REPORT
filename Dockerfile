# CEO 보고 사이트 (Cloud Run). 화면을 빌드하고, 작은 Node 서버가 IAP 확인 뒤 내려 준다. 회사 자료는 들어가지 않는다.
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
COPY web/package.json web/
COPY extension/package.json extension/
RUN npm ci --workspace web --include-workspace-root=false --no-audit --no-fund
COPY web/ web/
RUN npm run -w web build

FROM node:22-alpine
ENV NODE_ENV=production PORT=8080 WEB_ROOT=/app/web
WORKDIR /app
COPY server/server.mjs server/iap.mjs server/
COPY --from=build /app/web/dist web/
USER node
EXPOSE 8080
CMD ["node", "server/server.mjs"]
