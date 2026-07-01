# SolidWorks 执行摘要

- 零件族: `cnc_mount`
- 执行模式: `solidworks_com_serial`
- 单位策略: plan uses mm; SolidWorks API receives meters via sw_connect.mm()

## 步骤

1. `close_same_name_documents` -> `sw_session.SolidWorksSession.close` [ready]
2. `new_part` -> `sw_session.SolidWorksSession.new_part` [ready]
3. `base_plate` -> `sw_part.sketch_rectangle + sw_part.extrude_boss` [ready]
4. `outer_fillet_and_chamfer` -> `FeatureFillet / InsertFeatureChamfer with edge.Select2` [ready]
5. `pockets` -> `sw_part.sketch_rectangle or sketch_slot + extrude_cut` [ready]
6. `through_holes` -> `sw_part.sketch_circle + extrude_cut` [ready]
7. `mouth_chamfers` -> `InsertFeatureChamfer with circle edge selection` [ready]
8. `custom_properties` -> `model.Extension.CustomPropertyManager` [ready]
9. `save_export_review` -> `session.save + session.export + sw_review.run_review` [ready]

## 特征门禁

- `BasePlate` (base_plate), required=True
- `OuterCornerFillet` (fillet), required=True；降级：若圆角求解失败，降级为 R4 或逐边添加。
- `TopEdgeChamfer` (chamfer), required=True；降级：若整圈倒角失败，按边对象分组选择后重试。
- `CornerMountingHoles` (through_hole_pattern), required=True
- `CenterShaftClearance` (through_hole), required=True
- `SideLighteningPockets` (pocket_pair), required=False；降级：若口袋与中心孔或固定孔冲突，缩小口袋或跳过并记录。
- `HoleMouthChamfers` (chamfer), required=True

## 停止条件

- SolidWorks preflight fails
- required base geometry feature returns None
- save/export output file missing or zero bytes
- review report marks previews blank
