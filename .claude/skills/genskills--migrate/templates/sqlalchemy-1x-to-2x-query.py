# Query API (1.x - legacy)
session.query(User).filter(User.name == 'alice').all()
session.query(User).get(1)

# Query API (2.x - select() style)
from sqlalchemy import select
session.execute(select(User).where(User.name == 'alice')).scalars().all()
session.get(User, 1)
