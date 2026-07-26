FROM golang:1.23-alpine AS build
WORKDIR /workspace/services/ddu-discovery
COPY libs /workspace/libs
COPY services/ddu-discovery ./
RUN go mod download
RUN CGO_ENABLED=0 go build -o /out/ddu-discovery ./...

FROM alpine:3.20
RUN apk add --no-cache ca-certificates
COPY --from=build /out/ddu-discovery /usr/local/bin/ddu-discovery
ENTRYPOINT ["/usr/local/bin/ddu-discovery"]
