FROM golang:1.23-alpine AS build
WORKDIR /workspace/services/ddu-lineage
COPY libs /workspace/libs
COPY services/ddu-lineage ./
RUN go mod download
RUN CGO_ENABLED=0 go build -o /out/ddu-lineage ./...

FROM alpine:3.20
RUN apk add --no-cache ca-certificates
COPY --from=build /out/ddu-lineage /usr/local/bin/ddu-lineage
ENTRYPOINT ["/usr/local/bin/ddu-lineage"]
