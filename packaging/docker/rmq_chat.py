"""Bounded chat listener operations against the project's own game broker."""
import base64

QUEUE = 'dst.chat.commands'


def expression(action, maximum=25):
    if action not in {'declare', 'delete', 'drain'}:
        raise ValueError('Unsupported chat queue operation.')
    if type(maximum) is not int or not 1 <= maximum <= 25:
        raise ValueError('Drain between 1 and 25 chat messages.')
    prefix = 'QName = rabbit_misc:r(<<"/">>, queue, <<"'+QUEUE+'">>),\n'
    if action == 'declare':
        return prefix + '''Args = [{<<"x-max-length">>,long,500},
 {<<"x-message-ttl">>,long,300000},
 {<<"x-overflow">>,longstr,<<"drop-head">>}],
rabbit_amqqueue:declare(QName,false,false,Args,none,<<"dst">>),
XName = rabbit_misc:r(<<"/">>,exchange,<<"chat.intercept">>),
rabbit_binding:add({binding,XName,<<"#">>,QName,[]},<<"dst">>),
io:format("DSTCHAT:declared~n").'''
    if action == 'delete':
        return prefix + '''case rabbit_amqqueue:lookup(QName) of
 {ok,Q} -> rabbit_amqqueue:delete(Q,false,false,<<"dst">>);
 _ -> ok
end,
io:format("DSTCHAT:deleted~n").'''
    return prefix + '''case rabbit_amqqueue:lookup(QName) of
 {ok,Q} ->
  F = fun(Loop,N) ->
   case N of
    0 -> ok;
    _ -> case rabbit_amqqueue:basic_get(Q,true,0,<<"dst">>,rabbit_queue_type:init()) of
     {ok,_C,{_QN,_QP,_MI,_RD,Msg},_S} ->
      Content = mc:protocol_state(Msg),
      Body = iolist_to_binary(lists:reverse(element(6,Content))),
      case byte_size(Body) =< 65536 of
       true -> io:format("MSG:~s~n",[base64:encode(Body)]);
       false -> ok
      end,
      Loop(Loop,N-1);
     _ -> ok
    end
   end
  end,
  F(F,''' + str(maximum) + ''');
 _ -> ok
end,
io:format("DSTCHAT:drained~n").'''


def operate(state, engine, action, maximum=25):
    code = expression(action, maximum)
    if action != 'delete':
        if state.get('desiredState') != 'running':
            raise ValueError('Start the battlegroup before listening for chat commands.')
        if state.get('operation', {}).get('phase') == 'running':
            raise ValueError('Chat commands wait until the server operation finishes.')
    broker = state.get('connections', {}).get('rmq-game', {})
    if not broker.get('id'):
        if action == 'delete':
            return {'messages': [], 'skipped': True}
        raise ValueError('The game message broker is unavailable.')
    observed = engine.assert_owned(broker['id'], state['id'], 'rmq-game')
    if observed['State'].get('Status') != 'running' or observed['State'].get('Health', {}).get('Status') != 'healthy':
        if action == 'delete':
            return {'messages': [], 'skipped': True}
        raise ValueError('The game message broker is not ready.')
    output = engine.exec_internal(broker['id'], state['id'], 'rmq-game',
                                 ['/opt/rabbitmq/sbin/rabbitmqctl', 'eval', code])
    marker = {'declare': 'declared', 'delete': 'deleted', 'drain': 'drained'}[action]
    if 'DSTCHAT:'+marker not in output.splitlines():
        raise ValueError('Chat queue operation was not confirmed.')
    messages = []
    for line in output.splitlines():
        if line.startswith('MSG:'):
            raw = base64.b64decode(line[4:], validate=True)
            if len(raw) > 65536 or len(messages) >= maximum:
                raise ValueError('Chat response exceeds the transport limit.')
            messages.append(raw.decode('utf-8'))
    return {'messages': messages, 'skipped': False}
