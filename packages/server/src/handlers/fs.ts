import { FileSystem } from "@opencode-ai/core/filesystem"
import { RelativePath } from "@opencode-ai/core/schema"
import { Effect } from "effect"
import { HttpServerResponse } from "effect/unstable/http"
import { HttpApiBuilder, HttpApiSchema } from "effect/unstable/httpapi"
import { Api } from "../api"
import { response } from "../location"

export const FileSystemHandler = HttpApiBuilder.group(Api, "server.fs", (handlers) =>
  Effect.gen(function* () {
    return handlers
      .handleRaw("fs.read", (ctx) =>
        Effect.gen(function* () {
          const file = yield* (yield* FileSystem.Service).read({
            path: RelativePath.make(
              decodeURIComponent(new URL(ctx.request.url, "http://localhost").pathname.slice(13)),
            ),
          })
          return HttpServerResponse.uint8Array(file.content, { contentType: file.mime })
        }),
      )
      .handle("fs.getFile", (ctx) =>
        response(
          Effect.gen(function* () {
            const fileSystem = yield* FileSystem.Service
            const path = RelativePath.make(
              decodeURIComponent(new URL(ctx.request.url, "http://localhost").pathname.slice("/api/fs/get/".length)),
            )
            const file = yield* fileSystem.read({ path })
            const text = file.mime.startsWith("text/") || /(json|xml|\+json|\+xml)/.test(file.mime)
            return {
              name: path,
              content: text ? Buffer.from(file.content).toString("utf8") : Buffer.from(file.content).toString("base64"),
              encoding: text ? "utf8" : "base64",
              mime: file.mime,
            }
          }),
        ),
      )
      .handle("fs.saveFile", (ctx) =>
        Effect.gen(function* () {
          const fs = yield* FileSystem.Service
          const path = RelativePath.make(
            decodeURIComponent(new URL(ctx.request.url, "http://localhost").pathname.slice("/api/fs/save/".length)),
          )
          yield* fs.write({ ...ctx.payload, path })
          return HttpApiSchema.NoContent.make()
        }),
      )
      .handle("fs.list", (ctx) =>
        response(
          Effect.gen(function* () {
            const fs = yield* FileSystem.Service
            return yield* fs.list(ctx.query)
          }),
        ),
      )
      .handle("fs.find", (ctx) =>
        response(
          Effect.gen(function* () {
            const fs = yield* FileSystem.Service
            return yield* fs.find(ctx.query)
          }),
        ),
      )
  }),
)
