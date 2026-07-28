FROM golang:1.23-alpine AS build
WORKDIR /workspace/services/ddu-ingest
COPY libs /workspace/libs
COPY services/ddu-ingest ./
RUN go mod download
RUN CGO_ENABLED=0 go build -o /out/ddu-ingest ./...

FROM alpine:3.20
RUN apk add --no-cache ca-certificates
COPY --from=build /out/ddu-ingest /usr/local/bin/ddu-ingest
ENTRYPOINT ["/usr/local/bin/ddu-ingest"]
