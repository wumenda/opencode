import { FileSystem } from "@opencode-ai/schema/filesystem"
import { Location } from "@opencode-ai/schema/location"
import { PositiveInt, RelativePath } from "@opencode-ai/schema/schema"
import { Schema } from "effect"
import { HttpApiEndpoint, HttpApiGroup, HttpApiSchema, OpenApi } from "effect/unstable/httpapi"
import { LocationQuery, locationQueryOpenApi } from "./location"

const ListQuery = Schema.Struct({
  ...LocationQuery.fields,
  path: RelativePath.pipe(Schema.optional),
})

const FindQuery = Schema.Struct({
  ...LocationQuery.fields,
  query: FileSystem.FindInput.fields.query,
  type: FileSystem.FindInput.fields.type,
  limit: Schema.NumberFromString.pipe(Schema.decodeTo(PositiveInt), Schema.optional),
})

const FileContent = Schema.Struct({
  name: Schema.String,
  content: Schema.String,
  encoding: Schema.Literals(["utf8", "base64"]),
  mime: Schema.String,
})

// save_file 的请求体不含 path，path 来自 URL 通配符段
const WritePayload = Schema.Struct({
  content: Schema.String,
  encoding: Schema.Literals(["utf8", "base64"]).pipe(Schema.optional),
})

export const FileSystemGroup = HttpApiGroup.make("server.fs")
  .add(
    HttpApiEndpoint.get("fs.read", "/api/fs/read/*", {
      query: LocationQuery,
      success: Schema.Uint8Array.pipe(HttpApiSchema.asUint8Array()),
    })
      .annotateMerge(locationQueryOpenApi)
      .annotateMerge(
        OpenApi.annotations({
          identifier: "v2.fs.read",
          summary: "Read file",
          description: "Serve one file relative to the requested location.",
        }),
      ),
  )
  .add(
    HttpApiEndpoint.get("fs.list", "/api/fs/list", {
      query: ListQuery,
      success: Location.response(Schema.Array(FileSystem.Entry)),
    })
      .annotateMerge(locationQueryOpenApi)
      .annotateMerge(
        OpenApi.annotations({
          identifier: "v2.fs.list",
          summary: "List directory",
          description: "List direct children of one directory relative to the requested location.",
        }),
      ),
  )
  .add(
    HttpApiEndpoint.get("fs.find", "/api/fs/find", {
      query: FindQuery,
      success: Location.response(Schema.Array(FileSystem.Entry)),
    })
      .annotateMerge(locationQueryOpenApi)
      .annotateMerge(
        OpenApi.annotations({
          identifier: "v2.fs.find",
          summary: "Find files",
          description: "Find recursively ranked filesystem entries relative to the requested location.",
        }),
      ),
  )
  .add(
    HttpApiEndpoint.get("fs.getFile", "/api/fs/get/*", {
      query: LocationQuery,
      success: Location.response(FileContent),
    })
      .annotateMerge(locationQueryOpenApi)
      .annotateMerge(
        OpenApi.annotations({
          identifier: "v2.fs.getFile",
          summary: "Get file",
          description: "Read one file relative to the requested location as utf8 or base64 content.",
        }),
      ),
  )
  .add(
    HttpApiEndpoint.put("fs.saveFile", "/api/fs/save/*", {
      query: LocationQuery,
      payload: WritePayload,
      success: HttpApiSchema.NoContent,
    })
      .annotateMerge(locationQueryOpenApi)
      .annotateMerge(
        OpenApi.annotations({
          identifier: "v2.fs.saveFile",
          summary: "Save file",
          description: "Write text or binary content to one path relative to the requested location.",
        }),
      ),
  )
  .annotateMerge(
    OpenApi.annotations({
      title: "filesystem",
      description: "Experimental location-scoped filesystem routes.",
    }),
  )
