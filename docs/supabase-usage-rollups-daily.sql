create materialized view if not exists public.usage_rollups_daily as
select
    user_id,
    date_trunc('day', created_at at time zone 'utc')::date as usage_date,
    sum(request_count)::integer as request_count,
    sum(prompt_tokens)::integer as prompt_tokens,
    sum(completion_tokens)::integer as completion_tokens,
    sum(total_tokens)::integer as total_tokens
from public.usage_events
group by user_id, date_trunc('day', created_at at time zone 'utc')::date;

create unique index if not exists usage_rollups_daily_user_date_idx
on public.usage_rollups_daily (user_id, usage_date);

-- Refresh manually or from a scheduled job when you want faster dashboard reads.
-- The runtime quota checks currently read from usage_events directly so this view is optional.