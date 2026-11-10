"""创建 VS1 本地演示数据。"""

from sqlmodel import Session

from app.core.db import engine, init_db
from app.core.seed import seed_vs1_demo_data


def main() -> None:
    """初始化首个管理员并幂等写入四类角色、Team 和两名处理人。"""

    with Session(engine) as session:
        init_db(session)
        seed_vs1_demo_data(session)


if __name__ == "__main__":
    main()
