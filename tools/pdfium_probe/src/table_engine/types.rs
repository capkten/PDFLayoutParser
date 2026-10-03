// Generated pure Rust types for table_engine
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub enum OwnedValue {
    Null,
    Bool(bool),
    Integer(i64),
    Float(f64),
    String(String),
    Array(Vec<OwnedValue>),
    Object(BTreeMap<String, OwnedValue>),
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PageDto {
    pub schema_version: i64,
    pub width: f64,
    pub height: f64,
    pub rotation: i64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Rect4 {
    pub schema_version: i64,
    pub x0: f64,
    pub y0: f64,
    pub x1: f64,
    pub y1: f64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Line4 {
    pub schema_version: i64,
    pub x0: f64,
    pub y0: f64,
    pub x1: f64,
    pub y1: f64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct LineDto {
    pub schema_version: i64,
    pub rect: Rect4,
    pub width: Option<f64>,
    pub color: Option<f64>,
    pub source_order: i64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DrawingDto {
    pub schema_version: i64,
    pub kind: String,
    pub lines: Vec<LineDto>,
    pub rect: Rect4,
    pub fill: Option<OwnedValue>,
    pub stroke: Option<OwnedValue>,
    pub clip: Option<Rect4>,
    pub source_order: i64,
    pub color: Option<OwnedValue>,
    pub opacity: Option<f64>,
    pub fill_opacity: Option<f64>,
    pub width: Option<f64>,
    pub items: Option<Vec<OwnedValue>>,
    pub extra: BTreeMap<String, OwnedValue>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct OrderedRectDto {
    pub schema_version: i64,
    pub id: i64,
    pub rect: Rect4,
    pub order: i64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct CharacterDto {
    pub schema_version: i64,
    pub text: String,
    pub rect: Rect4,
    pub order: i64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct WordDto {
    pub schema_version: i64,
    pub text: String,
    pub rect: Rect4,
    pub order: i64,
    pub block: Option<i64>,
    pub line: Option<i64>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SourcePositionDto {
    pub schema_version: i64,
    pub block: i64,
    pub line: i64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct NativeSpanDto {
    pub schema_version: i64,
    pub text: String,
    pub rect: Rect4,
    pub font: Option<String>,
    pub size: Option<f64>,
    pub flags: Option<i64>,
    pub order: i64,
    pub characters: Vec<CharacterDto>,
    pub source_position: SourcePositionDto,
    pub block: i64,
    pub line: i64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
/// Snapshot input extends the native span representation with the complete
/// raw source position captured from PyMuPDF.  Native text stages keep using
/// NativeSpanDto, whose historical block/line source position is sufficient
/// for their current algorithms.
pub struct NativeSpanInputDto {
    pub span: NativeSpanDto,
    pub raw_source_position: Vec<i64>,
    /// Snapshot-only extension preserving each character's complete source position.
    pub character_raw_source_positions: Vec<Vec<i64>>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TextLineDto {
    pub schema_version: i64,
    pub rect: Rect4,
    pub spans: Vec<NativeSpanInputDto>,
    pub source_position: Vec<i64>,
    pub source_order: i64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TextBlockDto {
    pub schema_version: i64,
    pub block_type: Option<i64>,
    pub rect: Rect4,
    pub lines: Vec<TextLineDto>,
    pub source_position: Vec<i64>,
    pub source_order: i64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ExtractionOptionsDto {
    pub schema_version: i64,
    pub options: BTreeMap<String, OwnedValue>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PageSnapshotDto {
    pub schema_version: i64,
    pub page_index: i64,
    pub page: PageDto,
    pub page_y0: f64,
    pub text_blocks: Vec<TextBlockDto>,
    pub spans: Vec<NativeSpanInputDto>,
    pub words: Vec<WordDto>,
    pub drawings: Vec<DrawingDto>,
    pub allowed_regions: Vec<RegionDto>,
    pub excluded_regions: Vec<RegionDto>,
    pub extraction_options: ExtractionOptionsDto,
    /// Snapshot-only extensions for records whose shared algorithm DTOs predate
    /// the full PyMuPDF source-position shape.
    pub word_raw_source_positions: Vec<Vec<i64>>,
    pub drawing_raw_source_positions: Vec<Vec<i64>>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TextRunEvidenceDto {
    pub schema_version: i64,
    pub source_positions: Vec<SourcePositionDto>,
    pub fonts: Vec<Option<String>>,
    pub sizes: Vec<Option<f64>>,
    pub flags: Vec<Option<i64>>,
    pub source_fragment_indices: Option<Vec<i64>>,
    pub source_fragment_counts: Option<Vec<i64>>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TextRunDto {
    pub schema_version: i64,
    pub text: String,
    pub rect: Rect4,
    pub span_refs: Vec<i64>,
    pub source_start: i64,
    pub source_end: i64,
    pub order: i64,
    pub flow_start: Option<i64>,
    pub flow_end: Option<i64>,
    pub evidence: Option<TextRunEvidenceDto>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AtomDto {
    pub schema_version: i64,
    pub text: String,
    pub rect: Rect4,
    pub run_refs: Vec<i64>,
    pub row_hint: Option<i64>,
    pub col_hint: Option<i64>,
    pub col_end_hint: Option<i64>,
    pub order: i64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ColumnBandDto {
    pub schema_version: i64,
    pub x0: f64,
    pub x1: f64,
    pub source_atoms: Vec<i64>,
    pub order: i64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RegionDto {
    pub schema_version: i64,
    pub rect: Rect4,
    pub source_order: i64,
    pub allowed: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct GridDto {
    pub schema_version: i64,
    pub rows: i64,
    pub cols: i64,
    pub row_edges: Vec<f64>,
    pub col_edges: Vec<f64>,
    pub occupancy: Vec<Vec<Option<i64>>>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PhysicalCell {
    pub schema_version: i64,
    pub text: String,
    pub rect: Rect4,
    pub row: i64,
    pub col: i64,
    pub colspan: i64,
    pub source_refs: Vec<i64>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct CellDto {
    pub schema_version: i64,
    pub text: String,
    pub row: i64,
    pub col: i64,
    pub rect: Rect4,
    pub rowspan: i64,
    pub colspan: i64,
    pub source: Option<PhysicalCell>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct LogicalGridDto {
    pub schema_version: i64,
    pub grid: GridDto,
    pub cells: Vec<CellDto>,
    pub empty_slots: Vec<Vec<i64>>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TableCandidateDto {
    pub schema_version: i64,
    pub rect: Rect4,
    pub source: String,
    pub confidence: Option<f64>,
    pub rows: i64,
    pub cols: i64,
    pub cells: Vec<CellDto>,
    pub has_wired_lines: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RowClusterDto {
    pub schema_version: i64,
    pub row_index: i64,
    pub y0: f64,
    pub y1: f64,
    pub item_indices: Vec<i64>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ColumnClusterDto {
    pub schema_version: i64,
    pub col_index: i64,
    pub x0: f64,
    pub x1: f64,
    pub item_indices: Vec<i64>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct OutputOrderMode {
    pub schema_version: i64,
    pub value: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct StructureConfig {
    pub schema_version: i64,
    pub line_tolerance: f64,
    pub row_tolerance: f64,
    pub column_tolerance: f64,
    pub span_tolerance: f64,
    pub numeric_tolerance: f64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct BackgroundDto {
    pub schema_version: i64,
    pub rect: Rect4,
    pub color: Option<f64>,
    pub opacity: Option<f64>,
    pub source_order: i64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct BackgroundGroupDto {
    pub schema_version: i64,
    pub rect: Rect4,
    pub row_index: i64,
    pub source_indices: Vec<i64>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RowBandDto {
    pub schema_version: i64,
    pub rect: Rect4,
    pub row_index: i64,
    pub source_backgrounds: Vec<i64>,
    pub words: Vec<WordDto>,
    pub cells: Vec<CellDto>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PersonalCreditInput {
    pub schema_version: i64,
    pub page: PageDto,
    pub spans: Vec<NativeSpanDto>,
    pub words: Vec<WordDto>,
    pub allowed_regions: Vec<RegionDto>,
    pub excluded_regions: Vec<RegionDto>,
    pub wired_line_tolerance: f64,
    pub candidate_tables: Option<Vec<TableCandidateDto>>,
    pub supplement_rust_candidates: bool,
    pub snapshot: Option<PageSnapshotDto>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PersonalCreditOutput {
    pub schema_version: i64,
    pub tables: Vec<TableCandidateDto>,
    pub diagnostics: Vec<DiagnosticDto>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct NativeRecoveryInput {
    pub schema_version: i64,
    pub page: PageDto,
    pub spans: Vec<NativeSpanDto>,
    pub region: RegionDto,
    pub config: StructureConfig,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct NativeRecoveryOutput {
    pub schema_version: i64,
    pub candidates: Vec<TableCandidateDto>,
    pub atoms: Vec<AtomDto>,
    pub diagnostics: Vec<DiagnosticDto>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct NativeRegionInput {
    pub schema_version: i64,
    pub region: RegionDto,
    pub atoms: Vec<AtomDto>,
    pub bands: Vec<ColumnBandDto>,
    pub atom_evidence: Option<Vec<AtomEvidenceDto>>,
    pub band_evidence: Option<Vec<BandEvidenceDto>>,
    pub output_mode: String,
    pub config: StructureConfig,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct AtomEvidenceDto {
    pub flow_start: i64,
    pub flow_end: i64,
    pub source_blocks: Vec<i64>,
    pub source_line_start: i64,
    pub source_line_end: i64,
    pub source_position_known: bool,
    pub column_id: Option<i64>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct BandEvidenceDto {
    pub id: i64,
    pub kind: Option<String>,
    pub support: i64,
    pub y_support: i64,
    pub parent_x0: Option<f64>,
    pub parent_x1: Option<f64>,
    pub parent_leaf_count: Option<i64>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct NativeRegionOutput {
    pub schema_version: i64,
    pub grid: LogicalGridDto,
    pub cells: Vec<CellDto>,
    pub diagnostics: Vec<DiagnosticDto>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct WirelessRecoveryInput {
    pub schema_version: i64,
    pub page: PageDto,
    pub spans: Vec<NativeSpanDto>,
    pub regions: Vec<RegionDto>,
    pub config: StructureConfig,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct WirelessRecoveryOutput {
    pub schema_version: i64,
    pub candidates: Vec<TableCandidateDto>,
    pub diagnostics: Vec<DiagnosticDto>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ZebraInput {
    pub schema_version: i64,
    pub page: PageDto,
    pub backgrounds: Vec<BackgroundDto>,
    pub words: Vec<WordDto>,
    pub region: RegionDto,
    pub config: StructureConfig,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct EnglishGridInput {
    pub schema_version: i64,
    pub region: RegionDto,
    pub words: Vec<WordDto>,
    pub backgrounds: Vec<BackgroundDto>,
    pub horizontal_lines: Vec<f64>,
    pub horizontal_line_lengths: Vec<f64>,
    pub columns: Vec<ColumnBandDto>,
    pub config: StructureConfig,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct GeneralWirelessInput {
    pub schema_version: i64,
    pub region: RegionDto,
    pub atoms: Vec<AtomDto>,
    pub bands: Vec<ColumnBandDto>,
    pub config: StructureConfig,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct LegacyAlignmentInput {
    pub schema_version: i64,
    pub region: RegionDto,
    pub words: Vec<WordDto>,
    pub config: StructureConfig,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DiagnosticValueDto {
    pub schema_version: i64,
    pub kind: String,
    pub text: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DiagnosticDto {
    pub schema_version: i64,
    pub status: String,
    pub path: String,
    pub error_type: Option<String>,
    pub message: Option<String>,
    pub traceback_id: Option<String>,
    pub field: Option<String>,
    pub python_value: Option<DiagnosticValueDto>,
    pub rust_value: Option<DiagnosticValueDto>,
    pub classification: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct WiredRegionInput {
    pub schema_version: i64,
    pub page: PageDto,
    pub h_lines: Vec<LineDto>,
    pub v_lines: Vec<LineDto>,
    pub words: Vec<WordDto>,
    pub tolerance: f64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct WiredRegionOutput {
    pub schema_version: i64,
    pub regions: Vec<RegionDto>,
    pub grids: Vec<GridDto>,
    pub cells: Vec<CellDto>,
    pub diagnostics: Vec<DiagnosticDto>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct HeaderGridInput {
    pub schema_version: i64,
    pub grid: LogicalGridDto,
    pub config: StructureConfig,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct HeaderGridOutput {
    pub schema_version: i64,
    pub grid: LogicalGridDto,
    pub cells: Vec<CellDto>,
    pub diagnostics: Vec<DiagnosticDto>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct HeaderTokenInput {
    pub schema_version: i64,
    pub cells: Vec<CellDto>,
    pub config: StructureConfig,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct HeaderTokenOutput {
    pub schema_version: i64,
    pub cells: Vec<CellDto>,
    pub diagnostics: Vec<DiagnosticDto>,
}

impl Default for StructureConfig {
    fn default() -> Self {
        Self {
            schema_version: 1,
            line_tolerance: 2.0,
            row_tolerance: 2.0,
            column_tolerance: 2.0,
            span_tolerance: 2.0,
            numeric_tolerance: 2.0,
        }
    }
}
