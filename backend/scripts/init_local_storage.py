"""Initialize the two storage buckets for the standalone local Compose stack."""

import os

from minio import Minio


def main() -> None:
    client = Minio(
        os.environ["MINIO_ENDPOINT"],
        access_key=os.environ["MINIO_ACCESS_KEY"],
        secret_key=os.environ["MINIO_SECRET_KEY"],
        secure=False,
    )
    for name in ("datasets", "models"):
        if not client.bucket_exists(name):
            client.make_bucket(name)
        print(f"Storage bucket ready: {name}")


if __name__ == "__main__":
    main()
