FROM golang:1.23-alpine AS build
WORKDIR /workspace/services/ddu-graph-store
COPY libs /workspace/libs
COPY services/ddu-graph-store ./
RUN go mod download
RUN CGO_ENABLED=0 go build -o /out/ddu-graph-store ./...

FROM alpine:3.20
RUN apk add --no-cache ca-certificates
COPY --from=build /out/ddu-graph-store /usr/local/bin/ddu-graph-store
ENTRYPOINT ["/usr/local/bin/ddu-graph-store"]
