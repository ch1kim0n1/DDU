FROM golang:1.23-alpine AS build
WORKDIR /workspace/services/ddu-collector
COPY libs /workspace/libs
COPY services/ddu-collector ./
RUN go mod download
RUN CGO_ENABLED=0 go build -o /out/ddu-collector ./...

FROM alpine:3.20
RUN apk add --no-cache ca-certificates
COPY --from=build /out/ddu-collector /usr/local/bin/ddu-collector
ENTRYPOINT ["/usr/local/bin/ddu-collector"]
