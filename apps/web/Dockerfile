# Build context is the REPO ROOT, not apps/web -- see docker-compose.yml.
# apps/web is a Bun workspace member (`workspaces: ["apps/web"]`), so the root
# package.json and bun.lock have to be in the image for a frozen install to
# resolve at all.
FROM oven/bun:1.3.14

WORKDIR /repo

# Manifests first so `bun install` is cached independently of source edits.
COPY package.json bun.lock ./
COPY apps/web/package.json ./apps/web/package.json
RUN bun install --frozen-lockfile

COPY . .

# NEXT_PUBLIC_* is inlined into the client bundle at BUILD time, not read at
# runtime -- setting it in `environment:` later would do nothing. It also has to
# be an address the *browser* can reach, so it is localhost:8000 (the published
# port), never http://api:8000, which only resolves inside the compose network.
#
# Getting this wrong is not hypothetical: a production build that predated this
# variable silently called 127.0.0.1:8000 from real users' browsers.
ARG NEXT_PUBLIC_API_BASE=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE

RUN cd apps/web && bun run build

WORKDIR /repo/apps/web
EXPOSE 3000

CMD ["bun", "run", "start"]
