-- Create the webapp schema and the user registry table.
-- Target: PostgreSQL 18, database db_webapp.
-- Execution: run once by the official postgres image from /docker-entrypoint-initdb.d
-- when the data volume is empty, as the image superuser (POSTGRES_USER, webapp_owner).
-- Transaction: the whole file runs in one transaction; any error aborts initialization.
-- Side effects: creates schema webapp and table webapp.TB_USUARIO.
-- Rollback: drop the data volume before the first real use, or DROP SCHEMA webapp CASCADE.

BEGIN;

CREATE SCHEMA webapp;

COMMENT ON SCHEMA webapp IS
    'Objetos da aplicação webapp: cadastro de usuários exibido pela SPA.';

CREATE TABLE webapp.TB_USUARIO (
    ID_USUARIO bigint GENERATED ALWAYS AS IDENTITY,
    NO_USUARIO text NOT NULL,
    ED_EMAIL text NOT NULL,
    NO_LOCALIZACAO text,
    NO_ARQUIVO_IMAGEM text,
    DH_CRIACAO timestamp with time zone NOT NULL DEFAULT now(),
    DH_ATUALIZACAO timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT PK_TB_USUARIO PRIMARY KEY (ID_USUARIO),
    CONSTRAINT CC_TB_USUARIO_NO_USUARIO_01 CHECK (char_length(NO_USUARIO) BETWEEN 1 AND 200),
    CONSTRAINT CC_TB_USUARIO_ED_EMAIL_01 CHECK (
        char_length(ED_EMAIL) BETWEEN 3 AND 254 AND ED_EMAIL LIKE '%_@_%'
    ),
    CONSTRAINT CC_TB_USUARIO_NO_LOCALIZACAO_01 CHECK (
        char_length(NO_LOCALIZACAO) BETWEEN 1 AND 200
    ),
    CONSTRAINT CC_TB_USUARIO_NO_ARQUIVO_IMAGEM_01 CHECK (
        NO_ARQUIVO_IMAGEM ~ '^[0-9a-f]{32}\.(png|jpg|gif|webp)$'
    ),
    CONSTRAINT CC_TB_USUARIO_DH_ATUALIZACAO_01 CHECK (DH_ATUALIZACAO >= DH_CRIACAO)
);

-- Email uniqueness ignores letter case, so the index is on the lowered value.
CREATE UNIQUE INDEX IX_TB_USUARIO_01 ON webapp.TB_USUARIO (lower(ED_EMAIL));

COMMENT ON TABLE webapp.TB_USUARIO IS
    'Cadastro de usuários da aplicação webapp; cada linha representa uma pessoa cadastrada. '
    'Registros são removidos fisicamente na exclusão, sem histórico.';
COMMENT ON COLUMN webapp.TB_USUARIO.ID_USUARIO IS
    'Chave primária - tb_usuario. Identificador interno gerado pelo banco, sem significado de negócio.';
COMMENT ON COLUMN webapp.TB_USUARIO.NO_USUARIO IS
    'Nome de exibição do usuário, de 1 a 200 caracteres. Dado pessoal.';
COMMENT ON COLUMN webapp.TB_USUARIO.ED_EMAIL IS
    'Endereço de email do usuário, até 254 caracteres, único sem diferenciar maiúsculas. Dado pessoal.';
COMMENT ON COLUMN webapp.TB_USUARIO.NO_LOCALIZACAO IS
    'Localização informada pelo usuário, texto livre de 1 a 200 caracteres; nulo quando não informada.';
COMMENT ON COLUMN webapp.TB_USUARIO.NO_ARQUIVO_IMAGEM IS
    'Nome do arquivo da imagem de perfil no volume webapp-images, no formato <hex32>.<extensão>; '
    'nulo quando o usuário não possui imagem. Dado pessoal.';
COMMENT ON COLUMN webapp.TB_USUARIO.DH_CRIACAO IS
    'Instante de criação do registro, preenchido pelo banco com o início da transação.';
COMMENT ON COLUMN webapp.TB_USUARIO.DH_ATUALIZACAO IS
    'Instante da última alteração do registro, atualizado pela API a cada modificação.';
COMMENT ON INDEX webapp.IX_TB_USUARIO_01 IS
    'Garante email único sem diferenciar maiúsculas e minúsculas.';

COMMIT;
