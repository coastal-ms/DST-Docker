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
    return deliver(state,engine,code,len(fields))


def publish_courier(state,engine,courier):
    if not isinstance(courier,dict) or set(courier)!={'exchange','routingKey','body','type'}:
        raise ValueError('A typed courier message is required.')
    if courier['exchange']!='chat.whispers' or courier['type']!='12':
        raise ValueError('Unsupported courier channel.')
    route=courier['routingKey'];body=courier['body']
    if not isinstance(route,str) or not 1<=len(route)<=128 or not isinstance(body,str) or not 1<=len(body.encode('utf-8'))<=32768:
        raise ValueError('Courier message exceeds its limits.')
    envelope=json.loads(body)
    if not isinstance(envelope,dict) or envelope.get('Type')!='ECourierMessageType::TextChat' or not isinstance(envelope.get('Content'),str):
        raise ValueError('A text chat envelope is required.')
    encoded=lambda value: 'base64:decode(<<"'+base64.b64encode(value.encode('utf-8')).decode()+'">>)'
    code='''XName = rabbit_misc:r(<<"/">>, exchange, <<"chat.whispers">>),
X = rabbit_exchange:lookup_or_die(XName),
Body = '''+encoded(body)+''',
RoutingKey = '''+encoded(route)+''',
P = {list_to_atom("P_basic"), <<"Content">>, undefined, [], undefined,
     undefined, undefined, undefined, undefined, <<"dst-'''+uuid.uuid4().hex+'''">>, undefined,
     <<"12">>, <<"fls">>, <<"fls_backend">>, undefined},
Content = rabbit_basic:build_content(P, Body),
{ok, Msg} = rabbit_basic:message(XName, RoutingKey, Content),
rabbit_queue_type:publish_at_most_once(X, Msg),
{ok,enqueued,1}.'''
    return deliver(state,engine,code,1)


def deliver(state,engine,code,count):
    if state.get('desiredState')!='running':raise ValueError('Start the battlegroup before sending game commands.')
    broker=state.get('connections',{}).get('rmq-game',{})
    if not broker.get('id'):raise ValueError('The game message broker is unavailable.')
    observed=engine.assert_owned(broker['id'],state['id'],'rmq-game')
    if observed['State'].get('Health',{}).get('Status')!='healthy':raise ValueError('The game message broker is not ready.')
    output=engine.exec_internal(broker['id'],state['id'],'rmq-game',['/opt/rabbitmq/sbin/rabbitmqctl','eval',code])
    compact=''.join(output.split())
    if '{ok,enqueued,'+str(count)+'}' not in compact:raise ValueError('Broker delivery was not confirmed. Check the result before retrying.')
    return {'enqueued':count}
