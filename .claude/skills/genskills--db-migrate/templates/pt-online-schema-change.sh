pt-online-schema-change \
  --alter "ADD COLUMN phone VARCHAR(20)" \
  D=myapp,t=users \
  --execute \
  --max-lag=2 \
  --chunk-size=1000 \
  --critical-load="Threads_running=100"
