-- 监控maxkb对话的差评

-- DROP FUNCTION public.monitor_chat_update();

CREATE OR REPLACE FUNCTION public.monitor_chat_update()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE
    payload TEXT;
    asker_name TEXT;
	application_id uuid;
	application TEXT;
	node TEXT;
	message TEXT;
	run_time float;
	node_type TEXT;
BEGIN
	BEGIN
		-- 用户差评监控
	    IF NEW.vote_status = '1' THEN
			-- select * from application_chat
		    SELECT a.asker->>'username',a.application_id
			 INTO asker_name,application_id
			 FROM application_chat a
			WHERE a.id = NEW.chat_id;
			SELECT a.name INTO application FROM application a WHERE a.id =application_id;

	        payload := json_build_object(
	            'event_source', 'AI_CHAT_EVENT',
	            'type', 'CHAT_VOTE',
				'title','对话差评',
				'application',application,
	            'name', asker_name,
	            'id', NEW.id,
				'severity','告警',
	            'event_time', NEW.update_time,
	            'message', NEW.problem_text
	        )::text;
	        PERFORM pg_notify('AI_CHAT_EVENT', payload);
	        /*insert into event_log(event_type,playload,source_id,create_time)
			values('AI_CHAT_EVENT',CAST(payload as jsonb),new.id,new.update_time);*/
	    END IF;
    EXCEPTION WHEN OTHERS THEN
        -- 2. 捕获所有错误（OTHERS），将其记入 pg_log 为 WARNING，不中断事务
		insert into event_log(event_type,playload,source_id,create_time,message)
		values('AI_CHAT_EVENT_ERROR',CAST(payload as jsonb),new.id,new.update_time,SQLERRM);
        RAISE WARNING '触发器执行出错，错误详情: %, 错误代码: %', SQLERRM, SQLSTATE;
    END;
    RETURN NEW;
END;
$function$
;

-- 绑定到表触发器
CREATE TRIGGER trg_after_update_application_chat_record
AFTER UPDATE ON application_chat_record
FOR EACH row
when (
	old.vote_status is distinct from new.vote_status
)
EXECUTE FUNCTION monitor_chat_update();