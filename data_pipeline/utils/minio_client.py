import json
from typing import List, Dict
import boto3
from botocore.client import Config
import sys

class MinioClient:
    def __init__(self, endpoint: str, access_key: str, secret_key: str, secure: bool = False):
        self.s3 = boto3.client(
            's3',
            endpoint_url=f"http://{endpoint}" if not endpoint.startswith('http') else endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(
                signature_version='s3v4',
                connect_timeout=10,
                read_timeout=120,
                retries={'max_attempts': 3}
            ),
            use_ssl=secure
        )
        print("[*] Client S3 berhasil dibuat.", flush=True)

    def ensure_bucket(self, bucket_name: str):
        try:
            self.s3.head_bucket(Bucket=bucket_name)
        except:
            self.s3.create_bucket(Bucket=bucket_name)

    # Tambahkan parameter prefix
    def list_all_html_files(self, bucket_name: str, prefix: str = "") -> List[str]:
        print(f"[*] Menghubungi MinIO untuk list objek di '{bucket_name}' (Folder: {prefix})...", flush=True)
        files = []
        paginator = self.s3.get_paginator('list_objects_v2')

        try:
            # Tambahkan Prefix=prefix di sini
            for page in paginator.paginate(
                Bucket=bucket_name, 
                Prefix=prefix, 
                PaginationConfig={'PageSize': 1000}
            ):
                if 'Contents' in page:
                    # Filter file .html
                    batch = [obj['Key'] for obj in page['Contents'] if obj['Key'].endswith('.html')]
                    files.extend(batch)
                    sys.stdout.write(f"\r    > Terdata {len(files)} file...")
                    sys.stdout.flush()
                else:
                    break
        except Exception as e:
            print(f"\n[ERROR] Gagal list file: {e}", flush=True)
            return []

        print(f"\n[*] Selesai. Total {len(files)} file ditemukan.", flush=True)
        return sorted(files)

    def get_html_content(self, bucket_name: str, object_key: str) -> str:
        response = self.s3.get_object(Bucket=bucket_name, Key=object_key)
        return response['Body'].read().decode('utf-8')

    def upload_jsonl(self, bucket_name: str, data_list: List[Dict], object_name: str):
        jsonl_content = "\n".join([json.dumps(doc, ensure_ascii=False) for doc in data_list])
        self.s3.put_object(
            Bucket=bucket_name,
            Key=object_name,
            Body=jsonl_content.encode('utf-8'),
            ContentType='application/x-jsonlines'
        )