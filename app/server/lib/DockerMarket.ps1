# Native market purchases use PostgreSQL directly, without psql variables.
# Lock and revalidate the selected listing before creating a seller receipt.
function Invoke-DuneDockerBotPurchase {
    param(
        [string]$Ip,
        $Ident,
        [long]$OrderId,
        [long]$SellerId,
        [long]$ItemId,
        [string]$TemplateId,
        [long]$UnitPrice,
        [long]$Stack,
        [long]$OrderExpiry
    )
    $exchangeId = [long]$Ident.exchangeId
    $accessPointId = [long]$Ident.accessPointId
    $buyerId = [long]$Ident.ownerId
    if ($exchangeId -le 0 -or $accessPointId -le 0 -or $buyerId -le 0 -or
        $OrderId -le 0 -or $SellerId -le 0 -or $SellerId -eq $buyerId -or $ItemId -lt 0 -or
        [string]::IsNullOrWhiteSpace($TemplateId) -or $UnitPrice -lt 0 -or $Stack -le 0 -or $OrderExpiry -le 0) {
        return @{ok=$false;error='The native market purchase lacks an exact valid listing.'}
    }
    if ($UnitPrice -gt 0 -and [decimal]$Stack -gt ([decimal][long]::MaxValue / [decimal]$UnitPrice)) {
        return @{ok=$false;error='The native market purchase exceeds the supported balance range.'}
    }
    $template = $TemplateId.Replace("'", "''")
    $sql = @"
BEGIN;
CREATE TEMP TABLE dst_native_bot_purchase_result (purchased integer NOT NULL) ON COMMIT DROP;
INSERT INTO dst_native_bot_purchase_result VALUES (0);
DO `$dst_native_purchase`$
DECLARE
    listing record;
    held_item record;
    payment_id bigint;
    affected integer;
BEGIN
    SELECT o.id, o.item_id, s.initial_stack_size INTO listing
    FROM dune.dune_exchange_orders o
    JOIN dune.dune_exchange_sell_orders s ON s.order_id=o.id
    WHERE o.id=$OrderId::bigint AND o.exchange_id=$exchangeId::bigint
      AND o.owner_id=$SellerId::bigint AND o.template_id='$template'
      AND o.item_price=$UnitPrice::bigint AND o.is_npc_order=FALSE
      AND COALESCE(o.item_id,0)=$ItemId::bigint
    FOR UPDATE OF o,s;
    IF NOT FOUND THEN RETURN; END IF;

    IF $ItemId::bigint > 0 THEN
        SELECT i.id,i.template_id,i.stack_size INTO held_item
        FROM dune.items i WHERE i.id=$ItemId::bigint FOR UPDATE;
        IF NOT FOUND OR held_item.template_id IS DISTINCT FROM '$template'
           OR held_item.stack_size IS DISTINCT FROM $Stack::bigint THEN RETURN; END IF;
    ELSIF listing.initial_stack_size IS DISTINCT FROM $Stack::bigint THEN
        RETURN;
    END IF;

    UPDATE dune.dune_exchange_users
    SET solari_balance=solari_balance-($UnitPrice::bigint * $Stack::bigint)
    WHERE owner_id=$buyerId::bigint
      AND solari_balance >= ($UnitPrice::bigint * $Stack::bigint);
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected=0 THEN RETURN; END IF;
    IF affected<>1 THEN RAISE EXCEPTION 'The market buyer balance is ambiguous.'; END IF;

    INSERT INTO dune.dune_exchange_orders
      (exchange_id,access_point_id,owner_id,template_id,expiration_time,
       durability_cur,durability_max,item_price,category_mask,category_depth,is_npc_order)
    VALUES ($exchangeId,$accessPointId,$SellerId,'$template',$OrderExpiry,
            1.0,1.0,$UnitPrice,0,0,FALSE)
    RETURNING id INTO payment_id;
    INSERT INTO dune.dune_exchange_fulfilled_orders
      (order_id,source_order_id,completion_type,stack_size,original_order_id)
    VALUES (payment_id,NULL,4,$Stack,$OrderId);

    DELETE FROM dune.dune_exchange_sell_orders WHERE order_id=$OrderId;
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected<>1 THEN RAISE EXCEPTION 'The selected market sell row changed.'; END IF;
    DELETE FROM dune.dune_exchange_orders WHERE id=$OrderId;
    GET DIAGNOSTICS affected = ROW_COUNT;
    IF affected<>1 THEN RAISE EXCEPTION 'The selected market order changed.'; END IF;
    IF $ItemId::bigint > 0 THEN
        DELETE FROM dune.items WHERE id=$ItemId;
        GET DIAGNOSTICS affected = ROW_COUNT;
        IF affected<>1 THEN RAISE EXCEPTION 'The selected market item changed.'; END IF;
    END IF;
    UPDATE dst_native_bot_purchase_result SET purchased=1;
END;
`$dst_native_purchase`$;
SELECT purchased::text FROM dst_native_bot_purchase_result;
COMMIT;
"@
    $result = Invoke-DuneSqlQuery -Ip $Ip -Sql $sql -ReadOnly $false -MaxRows 1 -TimeoutSec 45
    if (-not $result.ok) { return @{ok=$false;error=[string]$result.error} }
    $rows = ConvertTo-DuneRowMaps -Result $result
    if ($rows.Count -ne 1 -or [string]$rows[0].purchased -cnotin @('0','1')) {
        return @{ok=$false;error='The committed native market purchase result could not be read. Refresh before retrying.'}
    }
    return @{ok=$true;purchased=([string]$rows[0].purchased -ceq '1')}
}
