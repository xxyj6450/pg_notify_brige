-- 监控maxkb的对话异常，包括差评、报错、节点异常、耗时长等问题
-- DROP FUNCTION public.monitor_chat();

CREATE OR REPLACE FUNCTION public.monitor_chat()
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
	    IF NEW.vote_status = '0' THEN
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

	    END IF;
    EXCEPTION WHEN OTHERS THEN

		insert into event_log(event_type,playload,source_id,create_time,message)
		values('CHAT_VOTE_ERROR',CAST(payload as jsonb),new.id,new.update_time,SQLERRM);
        -- 2. 捕获所有错误（OTHERS），将其记入 pg_log 为 WARNING，不中断事务
        RAISE WARNING '触发器执行出错，错误详情: %, 错误代码: %', SQLERRM, SQLSTATE;

    END;

	BEGIN
		-- 长耗时监控
	    IF NEW.run_time >= 200 THEN
		    SELECT a.asker->>'username',a.application_id
			 INTO asker_name,application_id
			 FROM application_chat a
			WHERE a.id = NEW.chat_id;
			SELECT a.name INTO application FROM application a WHERE a.id =application_id;
	        payload := json_build_object(
	            'event_source', 'AI_CHAT_EVENT',
	            'type', 'CHAT_SLOW',
				'title','对话回答速度慢',
				'application',application,
	            'name', asker_name,
	            'id', NEW.id,
				'severity','告警',
	            'event_time', NEW.update_time,
	            'message',NEW.problem_text
	        )::text;
	        PERFORM pg_notify('AI_CHAT_EVENT', payload);
	    END IF;
    EXCEPTION WHEN OTHERS THEN
        -- 2. 捕获所有错误（OTHERS），将其记入 pg_log 为 WARNING，不中断事务
		insert into event_log(event_type,playload,source_id,create_time,message)
		values('CHAT_SLOW_ERROR',CAST(payload as jsonb),new.id,new.update_time,SQLERRM);

        RAISE WARNING '触发器执行出错，错误详情: %, 错误代码: %', SQLERRM, SQLSTATE;

    END;

	BEGIN
		-- 执行错误
		SELECT value->>'name',value->>'err_message',value->>'run_time',value->>'type'
	    INTO node,message,run_time,node_type
	    FROM jsonb_each(NEW.details) -- 替换为您的实际 JSONB 字段名
	    WHERE cast(value->>'status' as int) <> 200 or NULLIF(value->>'err_message','') is not null
	    LIMIT 1;
	    IF NULLIF(node,'') is not null THEN
		    SELECT a.asker->>'username',a.application_id
			 INTO asker_name,application_id
			 FROM application_chat a
			WHERE a.id = NEW.chat_id;
			SELECT a.name INTO application FROM application a WHERE a.id =application_id;
	        payload := json_build_object(
	            'event_source', 'AI_CHAT_EVENT',
	            'type', 'CHAT_ERROR',
				'title','对话流程节点发生错误',
				'application',application,
	            'name', asker_name,
	            'id', NEW.id,
				'severity','严重',
	            'event_time', NEW.update_time,
				'node',node,
				'node_type',node_type,
	            'message', message
	        )::text;
	        PERFORM pg_notify('AI_CHAT_EVENT', payload);
		END IF;
    EXCEPTION WHEN OTHERS THEN
        -- 2. 捕获所有错误（OTHERS），将其记入 pg_log 为 WARNING，不中断事务
		insert into event_log(event_type,playload,source_id,create_time,message)
		values('CHAT_ERROR_ERROR',CAST(payload as jsonb),new.id,new.update_time,SQLERRM);

        RAISE WARNING '触发器执行出错，错误详情: %, 错误代码: %', SQLERRM, SQLSTATE;
    END;

	BEGIN
		-- 执行缓慢
		SELECT value->>'name',value->>'err_message',value->>'run_time',value->>'type'
	    INTO node,message,run_time,node_type
	    FROM jsonb_each(NEW.details) -- 替换为您的实际 JSONB 字段名
	    WHERE cast(value->>'run_time' as float) >=100
	    LIMIT 1;
	    IF NULLIF(node,'') is not null THEN
		    SELECT a.asker->>'username',a.application_id
			 INTO asker_name,application_id
			 FROM application_chat a
			WHERE a.id = NEW.chat_id;
			SELECT a.name INTO application FROM application a WHERE a.id =application_id;
	        payload := json_build_object(
	            'event_source', 'AI_CHAT_EVENT',
	            'type', 'CHAT_NODE_SLOW',
				'title','对话节点执行慢',
				'application',application,
	            'name', asker_name,
	            'id', NEW.id,
				'severity','告警',
	            'event_time', NEW.update_time,
				'node',node,
				'node_type',node_type,
	            'message', message
	        )::text;
	        PERFORM pg_notify('AI_CHAT_EVENT', payload);
	    END IF;
    EXCEPTION WHEN OTHERS THEN
		insert into event_log(event_type,playload,source_id,create_time,message)
		values('CHAT_NODE_SLOW_ERROR',CAST(payload as jsonb),new.id,new.update_time,SQLERRM);

        -- 2. 捕获所有错误（OTHERS），将其记入 pg_log 为 WARNING，不中断事务
        RAISE WARNING '触发器执行出错，错误详情: %, 错误代码: %', SQLERRM, SQLSTATE;
    END;

    RETURN NEW;
END;
$function$
;



CREATE TRIGGER trg_after_insert_application_chat_record
AFTER INSERT ON application_chat_record
FOR EACH ROW
EXECUTE FUNCTION monitor_chat();
