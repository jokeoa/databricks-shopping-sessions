FROM rust:1.99.1-slim-bookworm AS build
WORKDIR /build
COPY Cargo.toml Cargo.lock build.rs rust-toolchain.toml ./
COPY .cargo/ .cargo/
COPY src/ src/
RUN cargo build --release --locked --target x86_64-unknown-linux-gnu

FROM debian:bookworm-slim
RUN groupadd --gid 1000 app && useradd --uid 1000 --gid 1000 --no-create-home --home-dir /scratch app
COPY --from=build /build/target/x86_64-unknown-linux-gnu/release/shopping-sessions /app/shopping-sessions
USER 1000:1000
CMD ["/app/shopping-sessions"]
