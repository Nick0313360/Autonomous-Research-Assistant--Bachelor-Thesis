-- Enable RLS on a table
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;

-- Create policies
CREATE POLICY documents_tenant_isolation ON documents
  USING (tenant_id = current_setting('app.current_tenant')::UUID);

-- Force RLS even for table owner
ALTER TABLE documents FORCE ROW LEVEL SECURITY;

-- Migration note: Enabling RLS on a table with no policies blocks ALL access
-- for non-superusers. ALWAYS create at least one policy in the same transaction.
