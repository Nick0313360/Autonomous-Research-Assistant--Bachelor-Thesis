gh-ost \
  --host=replica.db.internal \
  --database=myapp \
  --table=users \
  --alter="ADD COLUMN phone VARCHAR(20)" \
  --execute \
  --allow-on-master \
  --max-lag-millis=1500 \
  --chunk-size=1000 \
  --throttle-control-replicas="replica1.db.internal"
