# Rust 迁移 DTO 合同

所有跨 FFI 类型均为显式 owned DTO，禁止动态字典。PDF 坐标使用左上原点、单位为 point；rotation 只允许 0、90、180、270；顺序稳定，source ref 从零开始，可空字段显式为 null，不允许 NaN/Inf。Python 独占 PyMuPDF Page、drawing、words、rawdict、native span 和渲染；Rust 不持有 Page、不回调 Python。诊断统一为 Vec<DiagnosticDto>，配置显式传入。

## DTO 注册表

PageDto={schema_version=1,width,height,rotation}; Rect4={schema_version=1,x0,y0,x1,y1}; Line4={schema_version=1,x0,y0,x1,y1}

LineDto={schema_version=1,rect,width?,color?,source_order}; DrawingDto={schema_version=1,kind,lines,rect,fill?,stroke?,clip?,source_order}

OrderedRectDto={schema_version=1,id,rect,order}; WordDto={schema_version=1,text,rect,order,block?,line?}; CharacterDto={schema_version=1,text,rect,order}

NativeSpanDto={schema_version=1,text,rect,font?,size?,flags?,order,characters,source_position,block,line}；其中 source_position:SourcePositionDto。

TextRunDto={schema_version=1,text,rect,span_refs,source_start,source_end,order}; AtomDto={schema_version=1,text,rect,run_refs,row_hint?,col_hint?,order}

ColumnBandDto={schema_version=1,x0,x1,source_atoms,order}; RegionDto={schema_version=1,rect,source_order,allowed}

WiredRegionInput={schema_version=1,page,h_lines,v_lines,words,tolerance}; WiredRegionOutput={schema_version=1,regions,grids,cells,diagnostics}

RowClusterDto={schema_version=1,row_index,y0,y1,item_indices}; ColumnClusterDto={schema_version=1,col_index,x0,x1,item_indices}; OutputOrderMode={schema_version=1,value}

TableCandidateDto={schema_version=1,rect,source,confidence?,rows,cols,cells}; GridDto={schema_version=1,rows,cols,row_edges,col_edges,occupancy}; LogicalGridDto={schema_version=1,grid,cells,empty_slots}

PhysicalCell={schema_version=1,text,rect,row,col,source_refs}; CellDto={schema_version=1,text,row,col,rect,rowspan,colspan,source?}

NativeRecoveryInput={schema_version=1,page,spans,region,config}; NativeRecoveryOutput={schema_version=1,candidates,atoms,diagnostics}; StructureConfig={schema_version=1,line_tolerance,row_tolerance,column_tolerance,span_tolerance,numeric_tolerance}

NativeRegionInput={schema_version=1,region,atoms,bands,config}; NativeRegionOutput={schema_version=1,grid,cells,diagnostics}; WirelessRecoveryInput={schema_version=1,page,spans,regions,config}; WirelessRecoveryOutput={schema_version=1,candidates,diagnostics}

BackgroundDto={schema_version=1,rect,color?,opacity?,source_order}; BackgroundGroupDto={schema_version=1,rect,row_index,source_indices}; RowBandDto={schema_version=1,rect,row_index,source_backgrounds,words,cells}

ZebraInput={schema_version=1,page,backgrounds,words,region,config}; EnglishGridInput={schema_version=1,region,words,backgrounds,config}; GeneralWirelessInput={schema_version=1,region,atoms,bands,config}; LegacyAlignmentInput={schema_version=1,region,words,config}

HeaderGridInput={schema_version=1,grid,config}; HeaderGridOutput={schema_version=1,grid,cells,diagnostics}; HeaderTokenInput={schema_version=1,cells,config}; HeaderTokenOutput={schema_version=1,cells,diagnostics}

DiagnosticValueDto={schema_version=1,kind:null|bool|number|string|json,text:String}; DiagnosticDto={schema_version=1,status,path,error_type?,message?,traceback_id?,field?,python_value?,rust_value?,classification?}

DiagnosticDto.status 仅允许 rust_fallback、rust_output_mismatch、invalid_input、unsupported、info；classification 仅允许 accepted、adaptation、defect、unsupported。mismatch 的 field 取路径末尾对象键，列表下标结尾使用 __list_length__，根差异使用 __root__。rust_fallback 和 rust_output_mismatch 必须进入结构化诊断，输出不一致不得静默回退。

已知配置：wired line_tolerance=2.3、merge_group_tol=0.3；wireless line_tolerance=2.0、color_tolerance=0.05、row_merge_tolerance=2.0。所有 Cell/网格跨度变化必须重新做 occupancy conflict 检查，并把未覆盖槽位物化为独立空 1x1 Cell。

## 严格字段类型、嵌套数组与 null 语义

以下定义逐字段列出所有 DTO。schema_version 固定为整数 1；number 必须是有限浮点数，integer 是零基整数，T[] 是稳定排序数组。带 ? 的字段必须存在且可为 JSON null；缺省值也必须序列化为 JSON null，不得改成空字符串、0、空数组或默认对象；无 ? 字段不得为 null。未列出的字段禁止出现。

- PageDto={schema_version:integer=1,width:number,height:number,rotation:0|90|180|270}。
- Rect4={schema_version:integer=1,x0:number,y0:number,x1:number,y1:number}；Line4={schema_version:integer=1,x0:number,y0:number,x1:number,y1:number}。
- LineDto={schema_version:integer=1,rect:Rect4,width:number?,color:number?,source_order:integer}。
- DrawingDto={schema_version:integer=1,kind:string,lines:LineDto[],rect:Rect4,fill:number?,stroke:number?,clip:Rect4?,source_order:integer}。
- OrderedRectDto={schema_version:integer=1,id:integer,rect:Rect4,order:integer}。
- WordDto={schema_version:integer=1,text:string,rect:Rect4,order:integer,block:integer?,line:integer?}；CharacterDto={schema_version:integer=1,text:string,rect:Rect4,order:integer}。
- SourcePositionDto={schema_version:integer=1,block:integer,line:integer}。
- NativeSpanDto={schema_version:integer=1,text:string,rect:Rect4,font:string?,size:number?,flags:integer?,order:integer,characters:CharacterDto[],source_position:SourcePositionDto,block:integer,line:integer}。NativeSpanDto.source_position 始终是上述对象，不是标量格式。
- TextRunDto={schema_version:integer=1,text:string,rect:Rect4,span_refs:integer[],source_start:integer,source_end:integer,order:integer}。
- AtomDto={schema_version:integer=1,text:string,rect:Rect4,run_refs:integer[],row_hint:integer?,col_hint:integer?,order:integer}。
- ColumnBandDto={schema_version:integer=1,x0:number,x1:number,source_atoms:integer[],order:integer}；RegionDto={schema_version:integer=1,rect:Rect4,source_order:integer,allowed:bool}。
- GridDto={schema_version:integer=1,rows:integer,cols:integer,row_edges:number[],col_edges:number[],occupancy:integer[][]}。
- PhysicalCell={schema_version:integer=1,text:string,rect:Rect4,row:integer,col:integer,source_refs:integer[]}。
- CellDto={schema_version:integer=1,text:string,row:integer,col:integer,rect:Rect4,rowspan:integer,colspan:integer,source:PhysicalCell?}；LogicalGridDto={schema_version:integer=1,grid:GridDto,cells:CellDto[],empty_slots:integer[][]}。
- TableCandidateDto={schema_version:integer=1,rect:Rect4,source:string,confidence:number?,rows:integer,cols:integer,cells:CellDto[]}。
- RowClusterDto={schema_version:integer=1,row_index:integer,y0:number,y1:number,item_indices:integer[]}；ColumnClusterDto={schema_version:integer=1,col_index:integer,x0:number,x1:number,item_indices:integer[]}；OutputOrderMode={schema_version:integer=1,value:string}。
- StructureConfig={schema_version:integer=1,line_tolerance:number,row_tolerance:number,column_tolerance:number,span_tolerance:number,numeric_tolerance:number}。
- WiredRegionInput={schema_version:integer=1,page:PageDto,h_lines:LineDto[],v_lines:LineDto[],words:WordDto[],tolerance:number}；WiredRegionOutput={schema_version:integer=1,regions:RegionDto[],grids:GridDto[],cells:CellDto[],diagnostics:DiagnosticDto[]}。
- NativeRecoveryInput={schema_version:integer=1,page:PageDto,spans:NativeSpanDto[],region:RegionDto,config:StructureConfig}；NativeRecoveryOutput={schema_version:integer=1,candidates:TableCandidateDto[],atoms:AtomDto[],diagnostics:DiagnosticDto[]}。
- NativeRegionInput={schema_version:integer=1,region:RegionDto,atoms:AtomDto[],bands:ColumnBandDto[],config:StructureConfig}；NativeRegionOutput={schema_version:integer=1,grid:LogicalGridDto,cells:CellDto[],diagnostics:DiagnosticDto[]}。
- WirelessRecoveryInput={schema_version:integer=1,page:PageDto,spans:NativeSpanDto[],regions:RegionDto[],config:StructureConfig}；WirelessRecoveryOutput={schema_version:integer=1,candidates:TableCandidateDto[],diagnostics:DiagnosticDto[]}。
- BackgroundDto={schema_version:integer=1,rect:Rect4,color:number?,opacity:number?,source_order:integer}；BackgroundGroupDto={schema_version:integer=1,rect:Rect4,row_index:integer,source_indices:integer[]}；RowBandDto={schema_version:integer=1,rect:Rect4,row_index:integer,source_backgrounds:integer[],words:WordDto[],cells:CellDto[]}。
- ZebraInput={schema_version:integer=1,page:PageDto,backgrounds:BackgroundDto[],words:WordDto[],region:RegionDto,config:StructureConfig}；EnglishGridInput={schema_version:integer=1,region:RegionDto,words:WordDto[],backgrounds:BackgroundDto[],config:StructureConfig}。
- GeneralWirelessInput={schema_version:integer=1,region:RegionDto,atoms:AtomDto[],bands:ColumnBandDto[],config:StructureConfig}；LegacyAlignmentInput={schema_version:integer=1,region:RegionDto,words:WordDto[],config:StructureConfig}。
- HeaderGridInput={schema_version:integer=1,grid:LogicalGridDto,config:StructureConfig}；HeaderGridOutput={schema_version:integer=1,grid:LogicalGridDto,cells:CellDto[],diagnostics:DiagnosticDto[]}。
- HeaderTokenInput={schema_version:integer=1,cells:CellDto[],config:StructureConfig}；HeaderTokenOutput={schema_version:integer=1,cells:CellDto[],diagnostics:DiagnosticDto[]}。
- DiagnosticValueDto={schema_version:integer=1,kind:null|bool|number|string|json,text:string}。
- DiagnosticDto={schema_version:integer=1,status:rust_fallback|rust_output_mismatch|invalid_input|unsupported|info,path:string,error_type:string?,message:string?,traceback_id:string?,field:string?,python_value:DiagnosticValueDto?,rust_value:DiagnosticValueDto?,classification:accepted|adaptation|defect|unsupported}。
所有诊断均为 Vec<DiagnosticDto>。null 表示值不存在，不得替换为默认值；错误映射通过 path 和 field 指向 DTO，列表长度使用 __list_length__，根差异使用 __root__。输入快照所有权在边界转移给 Rust，输出由 Rust 拥有并序列化；不得保存 Page 或回调 Python。中文/混合无线只消费 NativeSpanDto，不回读 page.get_text("words")、extract_zebra 或 legacy words 重建。
