-- 监控maxkb工具执行异常和耗时异常
-- DROP FUNCTION public.monitor_tool_record();

CREATE OR REPLACE FUNCTION public.monitor_tool_record()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE
    payload TEXT;
    tool_name TEXT;
	application TEXT;
BEGIN
	BEGIN
		-- 任务执行报错
	    IF NEW.state = 'FAILURE' THEN
	        SELECT name INTO tool_name FROM tool WHERE id = NEW.tool_id;
			SELECT name INTO application FROM application WHERE id = NEW.source_id;
	        payload := json_build_object(
	            'event_source', 'AI_TOOL_EVENT',
	            'type', 'TOOL_FAILURE',
				'title','工具执行错误',
				'application',application,
	            'name', tool_name,
	            'id', NEW.id,
	            'event_time', NEW.update_time,
				'severity','严重',
	            'message', NEW.meta ->> 'output'
	        )::text;
	        PERFORM pg_notify('AI_TOOL_EVENT', payload);

	    END IF;
    EXCEPTION WHEN OTHERS THEN

		insert into event_log(event_type,playload,source_id,create_time,message)
		values('AI_TOOL_EVENT_ERROR',CAST(payload as jsonb),new.id,new.update_time,SQLERRM);
        -- 2. 捕获所有错误（OTHERS），将其记入 pg_log 为 WARNING，不中断事务
        RAISE WARNING '触发器执行出错，错误详情: %, 错误代码: %', SQLERRM, SQLSTATE;

    END;

	BEGIN
		-- 慢任务执行
		IF NEW.run_time >= 5 THEN
		        SELECT name INTO tool_name FROM tool WHERE id = NEW.tool_id;
				SELECT name INTO application FROM application WHERE id = NEW.source_id;
		        payload := json_build_object(
		            'event_source', 'AI_TOOL_EVENT',
		            'type', 'TOOL_SLOW',
					'title','工具执行慢',
					'application',application,
		            'name', tool_name,
		            'id', NEW.id,
		            'event_time', NEW.update_time,
					'severity','告警',
		            'message', NEW.meta ->> 'output'
		        )::text;
		        PERFORM pg_notify('AI_TOOL_EVENT', payload);

		    END IF;
     EXCEPTION WHEN OTHERS THEN

		insert into event_log(event_type,playload,source_id,create_time,message)
		values('AI_TOOL_EVENT_ERROR',CAST(payload as jsonb),new.id,new.update_time,SQLERRM);
        -- 2. 捕获所有错误（OTHERS），将其记入 pg_log 为 WARNING，不中断事务
        RAISE WARNING '触发器执行出错，错误详情: %, 错误代码: %', SQLERRM, SQLSTATE;

    END;

    RETURN NEW;
END;
$function$
;

-- 绑定函数到表触发器
CREATE TRIGGER trg_after_insert_tool_record
AFTER INSERT ON tool_record
FOR EACH ROW
EXECUTE FUNCTION monitor_tool_record();