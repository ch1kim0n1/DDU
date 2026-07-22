FROM golang:1.22-alpine AS build
WORKDIR /src
COPY go.mod ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o /out/ddu-ingest ./...

FROM alpine:3.20
RUN apk add --no-cache ca-certificates
COPY --from=build /out/ddu-ingest /usr/local/bin/ddu-ingest
ENTRYPOINT ["/usr/local/bin/ddu-ingest"]
