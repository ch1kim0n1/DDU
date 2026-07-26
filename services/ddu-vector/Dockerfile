FROM golang:1.23-alpine AS build
WORKDIR /workspace/services/ddu-vector
COPY libs /workspace/libs
COPY services/ddu-vector ./
RUN go mod download
RUN CGO_ENABLED=0 go build -o /out/ddu-vector ./...

FROM alpine:3.20
RUN apk add --no-cache ca-certificates
COPY --from=build /out/ddu-vector /usr/local/bin/ddu-vector
ENTRYPOINT ["/usr/local/bin/ddu-vector"]
