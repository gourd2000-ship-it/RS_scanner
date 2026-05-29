"""
PostgreSQL 연결 테스트 및 테이블 확인 스크립트
"""
import sys
from pathlib import Path

# 프로젝트 루트를 Python path에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from sqlalchemy import create_engine, text, inspect
import os


def test_connection():
    """데이터베이스 연결 테스트"""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("❌ DATABASE_URL 환경변수가 설정되지 않았습니다.")
        return False

    print(f"📡 데이터베이스 연결 중: {database_url.split('@')[1] if '@' in database_url else database_url}")

    try:
        engine = create_engine(database_url)

        # 연결 테스트
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.scalar()
            print(f"✅ 연결 성공!")
            print(f"PostgreSQL 버전: {version.split(',')[0]}")
            print()

            # 테이블 목록 조회
            inspector = inspect(engine)
            tables = inspector.get_table_names()

            print(f"📊 생성된 테이블 목록 ({len(tables)}개):")
            for table in sorted(tables):
                print(f"  - {table}")
            print()

            # 각 테이블의 컬럼 수 확인
            print("📋 테이블 상세 정보:")
            for table in sorted(tables):
                columns = inspector.get_columns(table)
                indexes = inspector.get_indexes(table)
                print(f"  {table}:")
                print(f"    컬럼: {len(columns)}개")
                print(f"    인덱스: {len(indexes)}개")
            print()

            # 샘플 데이터 테스트
            print("🧪 샘플 데이터 테스트:")

            # 기존 데이터 확인
            result = conn.execute(text("SELECT COUNT(*) FROM benchmarks WHERE market = 'KOSPI'"))
            count = result.scalar()

            if count == 0:
                # benchmarks 테이블에 샘플 데이터 삽입
                conn.execute(text("""
                    INSERT INTO benchmarks (market, name, benchmark_code, created_at)
                    VALUES ('KOSPI', '코스피', 'KOSPI', CURRENT_TIMESTAMP)
                """))
                conn.commit()
                print("  ✅ 샘플 데이터 삽입 완료")
            else:
                print(f"  ℹ️  이미 데이터가 존재합니다 ({count}개)")

            # 데이터 조회
            result = conn.execute(text("SELECT * FROM benchmarks"))
            rows = result.fetchall()
            print(f"  benchmarks 테이블: {len(rows)}개 행")

            print()
            print("✅ 모든 테스트 통과!")
            return True

    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        return False


if __name__ == "__main__":
    success = test_connection()
    sys.exit(0 if success else 1)
