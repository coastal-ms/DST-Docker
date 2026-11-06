"""Typed publisher for the existing DST ServerCommand wire protocol."""
import base64
import json
import uuid

COMMANDS={'KickPlayer','UpdateAllWaterFillables','AwardXP','SkillsSetUnspentSkillPoints',
          'CleanPlayerInventory','ResetProgression','TeleportTo','TeleportToExact',
          'SkillsSetModuleLevel','AddItemToInventory','CheatScript','SpawnVehicleAt','ServiceBroadcast'}


def expression(fields,auth_token,spacing):
    if not isinstance(fields,list) or not 1<=len(fields)<=128:raise ValueError('A bounded command batch is required.')
    if type(spacing) is not int or not 0<=spacing<=5000 or len(fields)*spacing>15000:
        raise ValueError('Command pacing exceeds one broker operation.')
    if not isinstance(auth_token,str) or not 1<=len(auth_token)<=128:raise ValueError('Invalid game command authentication.')
    encoded=[]
    for field in fields:
        if not isinstance(field,dict) or field.get('ServerCommand') not in COMMANDS:raise ValueError('Unsupported game command.')
        inner=json.dumps(field,ensure_ascii=False,separators=(',',':'),allow_nan=False)
        outer=json.dumps({'Version':2,'AuthToken':auth_token,'MessageContent':inner},ensure_ascii=False,separators=(',',':'))
        encoded.append('base64:decode(<<"'+base64.b64encode(outer.encode()).decode()+'">>)')
    if sum(map(len,encoded))>64000:raise ValueError('The broker command batch is too large.')
    stamp=uuid.uuid4().hex
    return '''XName = rabbit_misc:r(<<"/">>, exchange, <<"heartbeats">>),
X = rabbit_exchange:lookup_or_die(XName),
Messages = ['''+','.join(encoded)+'''],
lists:foreach(fun(Outer) ->
    MsgId = list_to_binary("dst-'''+stamp+'''-" ++ integer_to_list(erlang:unique_integer([positive]))),
    P = {list_to_atom("P_basic"), <<"Content">>, undefined, [], undefined,
         undefined, undefined, undefined, undefined, MsgId, undefined,
         undefined, <<"fls">>, <<"fls_backend">>, undefined},
    Content = rabbit_basic:build_content(P, Outer),
    {ok, Msg} = rabbit_basic:message(XName, <<"notifications">>, Content),
    rabbit_queue_type:publish_at_most_once(X, Msg),
    timer:sleep('''+str(spacing)+''')
end, Messages),
{ok,enqueued,length(Messages)}.'''


def publish(state,engine,fields,auth_token,spacing):
    code=expression(fields,auth_token,spacing)
    if state.get('desiredState')!='running':raise ValueError('Start the battlegroup before sending game commands.')
    broker=state.get('connections',{}).get('rmq-game',{})
    if not broker.get('id'):raise ValueError('The game message broker is unavailable.')
    observed=engine.assert_owned(broker['id'],state['id'],'rmq-game')
    if observed['State'].get('Health',{}).get('Status')!='healthy':raise ValueError('The game message broker is not ready.')
    output=engine.exec_internal(broker['id'],state['id'],'rmq-game',['/opt/rabbitmq/sbin/rabbitmqctl','eval',code])
    compact=''.join(output.split())
    if '{ok,enqueued,'+str(len(fields))+'}' not in compact:raise ValueError('Broker delivery was not confirmed. Check the result before retrying.')
    return {'enqueued':len(fields)}
